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
from jang_app.services.managed_files import copy_file_atomic, link_or_copy_file, write_json_atomic
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
_FAILED_LOG_NAME = "extract-failed.log"
_DIAGNOSTIC_NAME_LIMIT = 8


class RvcTrainingExtractError(RuntimeError):
    """Raised when RVC pitch or feature extraction is incomplete."""


@dataclass(frozen=True)
class RvcTrainingExtractResult:
    experiment_dir: Path
    f0_files: tuple[Path, ...]
    f0_nsf_files: tuple[Path, ...]
    feature_files: tuple[Path, ...]
    log_path: Path


@dataclass(frozen=True)
class _ExtractOutputInventory:
    input_stems: frozenset[str]
    f0_stems: frozenset[str]
    f0_nsf_stems: frozenset[str]
    feature_stems: frozenset[str]

    @property
    def complete(self) -> bool:
        return (
            self.f0_stems == self.input_stems
            and self.f0_nsf_stems == self.input_stems
            and self.feature_stems == self.input_stems
        )

    @property
    def missing_f0(self) -> frozenset[str]:
        return self.input_stems - self.f0_stems

    @property
    def missing_f0_nsf(self) -> frozenset[str]:
        return self.input_stems - self.f0_nsf_stems

    @property
    def missing_features(self) -> frozenset[str]:
        return self.input_stems - self.feature_stems


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
        logger.info(
            "Starting RVC feature extraction: model=%s segments=%s device=%s "
            "backend=%s torch=%s cuda=%s",
            model_id,
            len(preprocess.wavs_16k),
            extraction_device,
            inspection.backend.value,
            inspection.torch_version or "unknown",
            inspection.cuda_version or "unknown",
        )
        _run_f0_extraction(
            runner,
            runtime,
            staging,
            extraction_device,
            accelerated=inspection.training_accelerated,
            runner_kwargs=runner_kwargs,
        )
        _report(progress, 45)
        raise_if_training_cancelled(cancellation)
        feature_launcher = prepare_rvc_script_launcher(
            staging / ".jjzero-launchers" / "extract_feature_print.py",
            runtime,
            runtime / "extract_feature_print.py",
        )
        _run_feature_extraction(
            runner,
            runtime,
            staging,
            extraction_device,
            gpu_index,
            feature_launcher,
            runner_kwargs,
        )
        _report(progress, 90)
        inventory = _extract_output_inventory(staging)
        logger.info("RVC extraction inventory: model=%s %s", model_id, _inventory_detail(inventory))
        if inspection.training_accelerated and not inventory.complete:
            detail = _inventory_detail(inventory)
            logger.warning(
                "RVC GPU extraction was incomplete; retrying missing outputs on CPU: "
                "model=%s %s",
                model_id,
                detail,
            )
            if output_callback is not None:
                output_callback(
                    "GPU extraction left incomplete files. Retrying only the missing outputs on CPU."
                )
            _recover_missing_outputs_on_cpu(
                inventory,
                runner,
                runtime,
                staging,
                feature_launcher,
                runner_kwargs,
            )
            _report(progress, 95)
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
        diagnostic_log = _preserve_failed_extract_log(staging, layout)
        detail = str(exc)
        if diagnostic_log is not None:
            detail = f"{detail} Diagnostic log: {diagnostic_log}"
        logger.error("RVC feature extraction failed: model=%s error=%s", model_id, detail)
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=detail)
        raise RvcTrainingExtractError(detail) from exc
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
    inventory = _extract_output_inventory(root)
    input_stems = set(inventory.input_stems)
    f0_files = _npy_files(root / "2a_f0")
    f0_nsf_files = _npy_files(root / "2b-f0nsf")
    feature_files = _npy_files(root / "3_feature768")
    if not input_stems:
        raise RvcTrainingExtractError("RVC extraction has no preprocessed input files.")
    f0_by_stem = {_f0_stem(path): path for path in f0_files}
    f0_nsf_by_stem = {_f0_stem(path): path for path in f0_nsf_files}
    feature_by_stem = {path.stem: path for path in feature_files}
    if not inventory.complete:
        detail = _inventory_detail(inventory)
        log_tail = _extract_log_tail(root)
        if log_tail:
            detail = f"{detail} RVC log tail: {log_tail}"
        raise RvcTrainingExtractError(f"RVC extraction outputs are incomplete: {detail}")

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
        get_logger().warning(
            "RVC extraction recovered after an upstream file-level failure: root=%s",
            root,
        )
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
        detail = result.output.strip()
        raise RvcTrainingExtractError(
            f"{label} failed with exit code {result.returncode}: "
            f"{detail or 'No process output was captured.'}"
        )


def _run_f0_extraction(
    runner: Callable[..., CommandResult],
    runtime: Path,
    staging: Path,
    device: str,
    *,
    accelerated: bool,
    runner_kwargs: dict[str, object],
) -> None:
    log_path = staging / "extract_f0_feature.log"
    result = runner(
        [
            str(runtime / "runtime" / "python.exe"),
            str(runtime / "extract_f0_rmvpe.py"),
            "1",
            "0",
            device,
            str(staging),
            "True" if accelerated else "False",
        ],
        **runner_kwargs,
    )
    if result.cancelled:
        raise RvcTrainingCancelled("RVC F0 extraction was stopped.")
    _append_failed_command_diagnostic(log_path, "RMVPE F0 extraction", result)
    _require_command_success("RMVPE F0 extraction", result)


def _run_feature_extraction(
    runner: Callable[..., CommandResult],
    runtime: Path,
    staging: Path,
    device: str,
    gpu_index: int,
    launcher: Path,
    runner_kwargs: dict[str, object],
) -> None:
    log_path = staging / "extract_f0_feature.log"
    result = runner(
        _feature_command(runtime, staging, device, gpu_index, launcher),
        **runner_kwargs,
    )
    if result.cancelled:
        raise RvcTrainingCancelled("RVC feature extraction was stopped.")
    _append_failed_command_diagnostic(log_path, "HuBERT feature extraction", result)
    _require_command_success("HuBERT feature extraction", result)


def _recover_missing_outputs_on_cpu(
    inventory: _ExtractOutputInventory,
    runner: Callable[..., CommandResult],
    runtime: Path,
    staging: Path,
    feature_launcher: Path,
    runner_kwargs: dict[str, object],
) -> None:
    if inventory.missing_f0 or inventory.missing_f0_nsf:
        _run_f0_extraction(
            runner,
            runtime,
            staging,
            "cpu",
            accelerated=False,
            runner_kwargs=runner_kwargs,
        )
    if inventory.missing_features:
        _run_feature_extraction(
            runner,
            runtime,
            staging,
            "cpu",
            0,
            feature_launcher,
            runner_kwargs,
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


def _extract_output_inventory(root: Path) -> _ExtractOutputInventory:
    return _ExtractOutputInventory(
        input_stems=frozenset(path.stem for path in (root / "1_16k_wavs").glob("*.wav")),
        f0_stems=frozenset(_f0_stem(path) for path in _npy_files(root / "2a_f0")),
        f0_nsf_stems=frozenset(_f0_stem(path) for path in _npy_files(root / "2b-f0nsf")),
        feature_stems=frozenset(path.stem for path in _npy_files(root / "3_feature768")),
    )


def _inventory_detail(inventory: _ExtractOutputInventory) -> str:
    expected = len(inventory.input_stems)
    return "; ".join(
        (
            f"expected={expected}",
            _stage_inventory_detail("F0", inventory.f0_stems, inventory.input_stems),
            _stage_inventory_detail("continuous F0", inventory.f0_nsf_stems, inventory.input_stems),
            _stage_inventory_detail("HuBERT", inventory.feature_stems, inventory.input_stems),
        )
    )


def _stage_inventory_detail(
    label: str,
    actual: frozenset[str],
    expected: frozenset[str],
) -> str:
    missing = expected - actual
    unexpected = actual - expected
    suffixes: list[str] = []
    if missing:
        suffixes.append(f"missing={_format_names(missing)}")
    if unexpected:
        suffixes.append(f"unexpected={_format_names(unexpected)}")
    suffix = f" ({', '.join(suffixes)})" if suffixes else ""
    return f"{label}={len(actual)}/{len(expected)}{suffix}"


def _format_names(names: frozenset[str]) -> str:
    ordered = sorted(names, key=str.casefold)
    visible = ordered[:_DIAGNOSTIC_NAME_LIMIT]
    suffix = f", +{len(ordered) - len(visible)} more" if len(ordered) > len(visible) else ""
    return f"[{', '.join(visible)}{suffix}]"


def _extract_log_tail(root: Path, *, limit: int = 2000) -> str:
    try:
        text = (root / "extract_f0_feature.log").read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    compact = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[-limit:]


def _append_failed_command_diagnostic(log_path: Path, label: str, result: CommandResult) -> None:
    if result.returncode == 0:
        return
    detail = result.output.strip() or "No process output was captured."
    try:
        with log_path.open("a", encoding="utf-8") as output:
            output.write(
                f"[JJZero] {label} failed with exit code {result.returncode}: {detail}\n"
            )
    except OSError:
        pass


def _preserve_failed_extract_log(
    staging: Path,
    layout: RvcModelPackageLayout,
) -> Path | None:
    source = staging / "extract_f0_feature.log"
    if not source.is_file():
        return None
    target = layout.model_dir / "training" / "diagnostics" / _FAILED_LOG_NAME
    try:
        return copy_file_atomic(source, target)
    except OSError:
        return None


def _npy_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob("*.npy"), key=lambda path: path.name.casefold()))


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    return layout.model_dir / "training" / "extract" / f".building-{uuid.uuid4().hex}"


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))
