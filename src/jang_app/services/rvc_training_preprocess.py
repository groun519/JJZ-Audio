from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_logging import get_logger
from jang_app.services.command import (
    CommandCancellation,
    CommandResult,
    run_cancellable_command,
    run_command,
)
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_artifacts import (
    publish_training_outputs,
    remove_training_staging,
)
from jang_app.services.rvc_training_control import (
    RvcTrainingCancelled,
    raise_if_training_cancelled,
)
from jang_app.services.rvc_training_dataset import (
    RvcTrainingSnapshot,
    RvcTrainingSnapshotStore,
)
from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_SAMPLE_RATE,
    inspect_rvc_training_runtime,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


PREPROCESS_MANIFEST_NAME = "jjzero_preprocess.json"
_PUBLISHED_OUTPUTS = (
    "0_gt_wavs",
    "1_16k_wavs",
    "preprocess.log",
    PREPROCESS_MANIFEST_NAME,
)
_INVALIDATED_OUTPUTS = (
    "2a_f0",
    "2b-f0nsf",
    "3_feature768",
    "extract_f0_feature.log",
    "jjzero_extract.json",
    "filelist.txt",
    "jjzero_filelist.json",
    "jjzero_index.json",
)


class RvcTrainingPreprocessError(RuntimeError):
    """Raised when the RVC training dataset cannot be preprocessed safely."""


@dataclass(frozen=True)
class RvcTrainingPreprocessResult:
    snapshot: RvcTrainingSnapshot
    experiment_dir: Path
    gt_wavs: tuple[Path, ...]
    wavs_16k: tuple[Path, ...]
    log_path: Path


def preprocess_rvc_training_dataset(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    *,
    worker_count: int | None = None,
    progress: Callable[[int], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
    command_runner: Callable[..., CommandResult] = run_command,
    cancellable_runner: Callable[..., CommandResult] = run_cancellable_command,
    cancellation: CommandCancellation | None = None,
) -> RvcTrainingPreprocessResult:
    runtime = runtime_root.expanduser().resolve()
    inspection = inspect_rvc_training_runtime(runtime)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingPreprocessError(f"RVC training runtime is incomplete: {missing}")

    snapshot_store = RvcTrainingSnapshotStore(model_id, layout)
    snapshot = snapshot_store.current()
    if snapshot is None:
        raise RvcTrainingPreprocessError("Create a reviewed training snapshot before preprocessing.")

    state_store = RvcTrainingStateStore(model_id, layout)
    state_store.update_phase(RvcTrainingPhase.PREPROCESS)
    workers = _worker_count(worker_count)
    staging = _staging_dir(layout)
    logger = get_logger()
    logger.info(
        "Starting RVC training preprocessing: model=%s inputs=%s workers=%s",
        model_id,
        len(snapshot.inputs),
        workers,
    )
    _report(progress, 0)
    try:
        raise_if_training_cancelled(cancellation)
        staging.mkdir(parents=True, exist_ok=False)
        completed_inputs = 0

        def handle_output(line: str) -> None:
            nonlocal completed_inputs
            if output_callback is not None:
                output_callback(line)
            if line.rstrip().endswith("->Suc."):
                completed_inputs += 1
                _report(progress, min(90, round(completed_inputs * 90 / len(snapshot.inputs))))

        runner = cancellable_runner if cancellation is not None else command_runner
        runner_kwargs = {
            "cwd": runtime,
            "env": build_rvc_environment(runtime),
            "output_callback": handle_output,
        }
        if cancellation is not None:
            runner_kwargs["cancellation"] = cancellation
        completed = runner(
            [
                str(runtime / "runtime" / "python.exe"),
                str(runtime / "trainset_preprocess_pipeline_print.py"),
                str(snapshot.input_dir),
                str(RVC_TRAINING_SAMPLE_RATE),
                str(workers),
                str(staging),
                "False",
            ],
            **runner_kwargs,
        )
        if completed.cancelled:
            raise RvcTrainingCancelled("RVC preprocessing was stopped.")
        if completed.returncode != 0:
            raise RvcTrainingPreprocessError(
                f"RVC preprocessing failed with exit code {completed.returncode}: {completed.output}"
            )
        _validate_preprocess_outputs(staging, len(snapshot.inputs))
        _write_preprocess_manifest(staging, snapshot)
        publish_training_outputs(
            staging,
            layout.experiment_dir,
            _PUBLISHED_OUTPUTS,
            invalidated_names=_INVALIDATED_OUTPUTS,
            backup_label="preprocess",
        )
        result = _preprocess_result(snapshot, layout.experiment_dir)
        state_store.update_phase(RvcTrainingPhase.PREPROCESSED)
        _report(progress, 100)
        logger.info(
            "RVC training preprocessing complete: model=%s segments=%s",
            model_id,
            len(result.gt_wavs),
        )
        return result
    except RvcTrainingCancelled:
        state_store.update_phase(RvcTrainingPhase.STOPPED)
        raise
    except Exception as exc:
        logger.error("RVC training preprocessing failed: model=%s error=%s", model_id, exc)
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=str(exc))
        if isinstance(exc, RvcTrainingPreprocessError):
            raise
        raise RvcTrainingPreprocessError(str(exc)) from exc
    finally:
        remove_training_staging(staging, layout.model_dir)


def load_rvc_preprocess_result(
    model_id: str,
    layout: RvcModelPackageLayout,
) -> RvcTrainingPreprocessResult:
    snapshot = RvcTrainingSnapshotStore(model_id, layout).current()
    if snapshot is None:
        raise RvcTrainingPreprocessError("Create a reviewed training snapshot before preprocessing.")
    return _preprocess_result(snapshot, layout.experiment_dir)


def _validate_preprocess_outputs(root: Path, expected_inputs: int) -> None:
    gt_wavs = _wav_files(root / "0_gt_wavs")
    wavs_16k = _wav_files(root / "1_16k_wavs")
    if not gt_wavs or not wavs_16k:
        raise RvcTrainingPreprocessError("RVC preprocessing created no usable audio segments.")
    if {path.stem for path in gt_wavs} != {path.stem for path in wavs_16k}:
        raise RvcTrainingPreprocessError("RVC preprocessing output pairs do not match.")
    log_path = root / "preprocess.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RvcTrainingPreprocessError("RVC preprocessing did not create a readable log.") from exc
    success_count = sum(line.rstrip().endswith("->Suc.") for line in log_text.splitlines())
    if success_count != expected_inputs:
        raise RvcTrainingPreprocessError(
            f"RVC preprocessing completed {success_count} of {expected_inputs} input files."
        )


def _preprocess_result(
    snapshot: RvcTrainingSnapshot,
    experiment_dir: Path,
) -> RvcTrainingPreprocessResult:
    _validate_preprocess_outputs(experiment_dir, len(snapshot.inputs))
    _validate_preprocess_manifest(experiment_dir, snapshot)
    return RvcTrainingPreprocessResult(
        snapshot=snapshot,
        experiment_dir=experiment_dir,
        gt_wavs=_wav_files(experiment_dir / "0_gt_wavs"),
        wavs_16k=_wav_files(experiment_dir / "1_16k_wavs"),
        log_path=experiment_dir / "preprocess.log",
    )


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    root = layout.model_dir / "training" / "preprocess"
    return root / f".building-{uuid.uuid4().hex}"


def _write_preprocess_manifest(root: Path, snapshot: RvcTrainingSnapshot) -> None:
    write_json_atomic(
        root / PREPROCESS_MANIFEST_NAME,
        {
            "version": 1,
            "dataset_fingerprint": snapshot.fingerprint,
            "input_count": len(snapshot.inputs),
            "segment_count": len(_wav_files(root / "0_gt_wavs")),
        },
    )


def _validate_preprocess_manifest(root: Path, snapshot: RvcTrainingSnapshot) -> None:
    path = root / PREPROCESS_MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingPreprocessError("RVC preprocess manifest cannot be read.") from exc
    if (
        data.get("version") != 1
        or data.get("dataset_fingerprint") != snapshot.fingerprint
        or data.get("input_count") != len(snapshot.inputs)
        or data.get("segment_count") != len(_wav_files(root / "0_gt_wavs"))
    ):
        raise RvcTrainingPreprocessError("RVC preprocess outputs belong to a different dataset.")


def _wav_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob("*.wav"), key=lambda path: path.name.casefold()))


def _worker_count(value: int | None) -> int:
    detected = os.cpu_count() or 1
    return max(1, min(int(value) if value is not None else detected, detected, 8))


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))
