from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jang_app.services.app_logging import get_logger
from jang_app.services.command import (
    CommandCancellation,
    CommandResult,
    run_cancellable_command,
    run_command,
)
from jang_app.services.managed_files import link_or_copy_file, write_json_atomic
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_script_launcher import prepare_rvc_script_launcher
from jang_app.services.rvc_training_artifacts import (
    publish_training_outputs,
    remove_training_staging,
)
from jang_app.services.rvc_training_control import (
    RvcTrainingCancelled,
    raise_if_training_cancelled,
)
from jang_app.services.rvc_training_preprocess import load_rvc_preprocess_result
from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_VERSION,
    RvcTrainingRuntimeInspection,
    inspect_rvc_training_runtime,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


EXTRACT_MANIFEST_NAME = "jjzero_extract.json"
_PUBLISHED_OUTPUTS = (
    "2a_f0",
    "2b-f0nsf",
    "3_feature768",
    "extract_f0_feature.log",
    EXTRACT_MANIFEST_NAME,
)
_INVALIDATED_OUTPUTS = ("filelist.txt", "jjzero_filelist.json", "jjzero_index.json")
_FAILURE_MARKERS = ("f0fail-", "f0_all_fail-", "traceback", "contains nan", "error:")


class RvcTrainingExtractError(RuntimeError):
    """Raised when RVC pitch or feature extraction is incomplete."""


@dataclass(frozen=True)
class RvcTrainingExtractResult:
    experiment_dir: Path
    f0_files: tuple[Path, ...]
    f0_nsf_files: tuple[Path, ...]
    feature_files: tuple[Path, ...]
    log_path: Path


def extract_rvc_training_features(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    *,
    gpu_index: int = 0,
    progress: Callable[[int], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
    command_runner: Callable[..., CommandResult] = run_command,
    cancellable_runner: Callable[..., CommandResult] = run_cancellable_command,
    cancellation: CommandCancellation | None = None,
    runtime_inspector: Callable[..., RvcTrainingRuntimeInspection] = inspect_rvc_training_runtime,
) -> RvcTrainingExtractResult:
    runtime = runtime_root.expanduser().resolve()
    inspection = runtime_inspector(runtime, check_cuda=True)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingExtractError(f"RVC training runtime is incomplete: {missing}")
    if not inspection.ready:
        raise RvcTrainingExtractError(
            inspection.cuda_error or "The RVC runtime cannot run feature extraction on this PC."
        )
    if inspection.training_accelerated and (
        gpu_index < 0 or gpu_index >= inspection.cuda_device_count
    ):
        raise RvcTrainingExtractError("The selected GPU is not available for RVC extraction.")

    preprocess = load_rvc_preprocess_result(model_id, layout)
    state_store = RvcTrainingStateStore(model_id, layout)
    state_store.update_phase(RvcTrainingPhase.EXTRACT)
    staging = _staging_dir(layout)
    logger = get_logger()
    _report(progress, 0)
    try:
        raise_if_training_cancelled(cancellation)
        _prepare_staging_inputs(preprocess.wavs_16k, staging)
        environment = build_rvc_environment(runtime)
        runner = cancellable_runner if cancellation is not None else command_runner
        runner_kwargs = {
            "cwd": runtime,
            "env": environment,
            "output_callback": output_callback,
        }
        if cancellation is not None:
            runner_kwargs["cancellation"] = cancellation
        extraction_device = (
            f"cuda:{gpu_index}" if inspection.training_accelerated else "cpu"
        )
        f0_result = runner(
            [
                str(runtime / "runtime" / "python.exe"),
                str(runtime / "extract_f0_rmvpe.py"),
                "1",
                "0",
                extraction_device,
                str(staging),
                "True" if inspection.training_accelerated else "False",
            ],
            **runner_kwargs,
        )
        if f0_result.cancelled:
            raise RvcTrainingCancelled("RVC F0 extraction was stopped.")
        _require_command_success("RMVPE F0 extraction", f0_result)
        _report(progress, 45)
        raise_if_training_cancelled(cancellation)
        feature_launcher = prepare_rvc_script_launcher(
            staging / ".jjzero-launchers" / "extract_feature_print.py",
            runtime,
            runtime / "extract_feature_print.py",
        )
        feature_result = runner(
            _feature_command(
                runtime,
                staging,
                extraction_device,
                gpu_index,
                feature_launcher,
            ),
            **runner_kwargs,
        )
        if feature_result.cancelled:
            raise RvcTrainingCancelled("RVC feature extraction was stopped.")
        _require_command_success("HuBERT feature extraction", feature_result)
        _report(progress, 90)
        result = _validate_extract_outputs(staging)
        _write_extract_manifest(staging, preprocess.snapshot.fingerprint, len(result.feature_files))
        publish_training_outputs(
            staging,
            layout.experiment_dir,
            _PUBLISHED_OUTPUTS,
            invalidated_names=_INVALIDATED_OUTPUTS,
            backup_label="extract",
        )
        result = load_rvc_extract_result(model_id, layout)
        state_store.update_phase(RvcTrainingPhase.FEATURES_READY)
        _report(progress, 100)
        logger.info(
            "RVC feature extraction complete: model=%s segments=%s",
            model_id,
            len(result.feature_files),
        )
        return result
    except RvcTrainingCancelled:
        state_store.update_phase(RvcTrainingPhase.STOPPED)
        raise
    except Exception as exc:
        logger.error("RVC feature extraction failed: model=%s error=%s", model_id, exc)
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=str(exc))
        if isinstance(exc, RvcTrainingExtractError):
            raise
        raise RvcTrainingExtractError(str(exc)) from exc
    finally:
        remove_training_staging(staging, layout.model_dir)


def load_rvc_extract_result(
    model_id: str,
    layout: RvcModelPackageLayout,
) -> RvcTrainingExtractResult:
    preprocess = load_rvc_preprocess_result(model_id, layout)
    result = _validate_extract_outputs(layout.experiment_dir)
    path = layout.experiment_dir / EXTRACT_MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingExtractError("RVC extraction manifest cannot be read.") from exc
    if (
        data.get("version") != 1
        or data.get("dataset_fingerprint") != preprocess.snapshot.fingerprint
        or data.get("feature_count") != len(result.feature_files)
    ):
        raise RvcTrainingExtractError("RVC extraction outputs belong to a different dataset.")
    return result


def _prepare_staging_inputs(sources: tuple[Path, ...], staging: Path) -> None:
    target_dir = staging / "1_16k_wavs"
    target_dir.mkdir(parents=True, exist_ok=False)
    for source in sources:
        link_or_copy_file(source, target_dir / source.name)


def _validate_extract_outputs(root: Path) -> RvcTrainingExtractResult:
    input_stems = {path.stem for path in (root / "1_16k_wavs").glob("*.wav")}
    f0_files = _npy_files(root / "2a_f0")
    f0_nsf_files = _npy_files(root / "2b-f0nsf")
    feature_files = _npy_files(root / "3_feature768")
    if not input_stems:
        raise RvcTrainingExtractError("RVC extraction has no preprocessed input files.")
    f0_by_stem = {_f0_stem(path): path for path in f0_files}
    f0_nsf_by_stem = {_f0_stem(path): path for path in f0_nsf_files}
    feature_by_stem = {path.stem: path for path in feature_files}
    if not (
        set(f0_by_stem) == input_stems
        and set(f0_nsf_by_stem) == input_stems
        and set(feature_by_stem) == input_stems
    ):
        raise RvcTrainingExtractError("RVC extraction output files do not match preprocessed inputs.")

    for stem in sorted(input_stems):
        coarse = _load_array(f0_by_stem[stem], expected_dimensions=1)
        continuous = _load_array(f0_nsf_by_stem[stem], expected_dimensions=1)
        feature = _load_array(feature_by_stem[stem], expected_dimensions=2)
        if coarse.shape != continuous.shape:
            raise RvcTrainingExtractError(f"F0 arrays have different lengths: {stem}")
        if not np.issubdtype(coarse.dtype, np.integer):
            raise RvcTrainingExtractError(f"Coarse F0 array is not integer data: {stem}")
        if np.min(coarse) < 1 or np.max(coarse) > 255:
            raise RvcTrainingExtractError(f"Coarse F0 values are outside the valid range: {stem}")
        if feature.shape[1] != 768:
            raise RvcTrainingExtractError(f"HuBERT feature width is not 768: {stem}")

    log_path = root / "extract_f0_feature.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RvcTrainingExtractError("RVC extraction did not create a readable log.") from exc
    lowered_log = log_text.casefold()
    if any(marker in lowered_log for marker in _FAILURE_MARKERS):
        raise RvcTrainingExtractError("RVC extraction log contains a failure.")
    return RvcTrainingExtractResult(
        experiment_dir=root,
        f0_files=tuple(f0_by_stem[stem] for stem in sorted(input_stems)),
        f0_nsf_files=tuple(f0_nsf_by_stem[stem] for stem in sorted(input_stems)),
        feature_files=tuple(feature_by_stem[stem] for stem in sorted(input_stems)),
        log_path=log_path,
    )


def _load_array(path: Path, *, expected_dimensions: int) -> np.ndarray:
    try:
        array = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RvcTrainingExtractError(f"RVC extraction array cannot be read: {path}") from exc
    if array.ndim != expected_dimensions or array.size == 0 or not np.isfinite(array).all():
        raise RvcTrainingExtractError(f"RVC extraction array is empty or invalid: {path}")
    return array


def _require_command_success(label: str, result: CommandResult) -> None:
    if result.returncode != 0:
        raise RvcTrainingExtractError(
            f"{label} failed with exit code {result.returncode}: {result.output}"
        )


def _feature_command(
    runtime: Path,
    staging: Path,
    device: str,
    gpu_index: int,
    launcher: Path,
) -> list[str]:
    command = [
        str(runtime / "runtime" / "python.exe"),
        str(launcher),
        device,
        "1",
        "0",
    ]
    if device.startswith("cuda"):
        command.append(str(gpu_index))
    command.extend((str(staging), RVC_TRAINING_VERSION))
    return command


def _write_extract_manifest(root: Path, fingerprint: str, feature_count: int) -> None:
    write_json_atomic(
        root / EXTRACT_MANIFEST_NAME,
        {
            "version": 1,
            "dataset_fingerprint": fingerprint,
            "feature_count": feature_count,
        },
    )


def _f0_stem(path: Path) -> str:
    return path.name.removesuffix(".wav.npy")


def _npy_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob("*.npy"), key=lambda path: path.name.casefold()))


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    return layout.model_dir / "training" / "extract" / f".building-{uuid.uuid4().hex}"


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))
