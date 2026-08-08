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
from jang_app.services.managed_files import copy_file_atomic, write_json_atomic
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
    RvcTrainingSnapshotInput,
    RvcTrainingSnapshotStore,
)
from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_SAMPLE_RATE,
    inspect_rvc_training_runtime,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


PREPROCESS_MANIFEST_NAME = "jjzero_preprocess.json"
PREPROCESS_MANIFEST_VERSION = 4
_FAILED_LOG_NAME = "preprocess-failed.log"
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
class RvcTrainingPreprocessFailure:
    input_name: str
    reason: str
    source_item_id: str = ""
    source_clip_id: str = ""


@dataclass(frozen=True)
class RvcTrainingPreprocessResult:
    snapshot: RvcTrainingSnapshot
    experiment_dir: Path
    gt_wavs: tuple[Path, ...]
    wavs_16k: tuple[Path, ...]
    log_path: Path
    successful_input_count: int
    failed_inputs: tuple[RvcTrainingPreprocessFailure, ...]

    @property
    def skipped_input_count(self) -> int:
        return len(self.failed_inputs)


@dataclass(frozen=True)
class _PreprocessValidation:
    successful_input_count: int
    failed_inputs: tuple[RvcTrainingPreprocessFailure, ...]


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
        validation = _validate_preprocess_outputs(staging, snapshot)
        _write_preprocess_manifest(staging, snapshot, validation)
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
            "RVC training preprocessing complete: model=%s inputs=%s skipped=%s segments=%s",
            model_id,
            result.successful_input_count,
            result.skipped_input_count,
            len(result.gt_wavs),
        )
        if result.failed_inputs:
            logger.warning(
                "RVC preprocessing skipped invalid training inputs: model=%s skipped=%s log=%s",
                model_id,
                result.skipped_input_count,
                result.log_path,
            )
            for failure in result.failed_inputs:
                logger.warning(
                    "RVC preprocessing skipped input: model=%s input=%s reason=%s",
                    model_id,
                    failure.input_name,
                    failure.reason,
                )
        return result
    except RvcTrainingCancelled:
        state_store.update_phase(RvcTrainingPhase.STOPPED)
        raise
    except Exception as exc:
        diagnostic_log = _preserve_failed_preprocess_log(staging, layout)
        detail = str(exc)
        if diagnostic_log is not None:
            detail = f"{detail} Diagnostic log: {diagnostic_log}"
        logger.error("RVC training preprocessing failed: model=%s error=%s", model_id, detail)
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=detail)
        raise RvcTrainingPreprocessError(detail) from exc
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


def _validate_preprocess_outputs(
    root: Path,
    snapshot: RvcTrainingSnapshot,
) -> _PreprocessValidation:
    log_path = root / "preprocess.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RvcTrainingPreprocessError("RVC preprocessing did not create a readable log.") from exc
    gt_wavs = _wav_files(root / "0_gt_wavs")
    wavs_16k = _wav_files(root / "1_16k_wavs")
    if not gt_wavs or not wavs_16k:
        raise RvcTrainingPreprocessError("RVC preprocessing created no usable audio segments.")
    if {path.stem for path in gt_wavs} != {path.stem for path in wavs_16k}:
        raise RvcTrainingPreprocessError("RVC preprocessing output pairs do not match.")
    produced_indices = _produced_input_indices(gt_wavs, len(snapshot.inputs))
    validation = _classify_preprocess_outputs(log_text, snapshot, produced_indices)
    if validation.successful_input_count <= 0:
        raise RvcTrainingPreprocessError("RVC preprocessing created no usable audio segments.")
    return validation


def _preprocess_result(
    snapshot: RvcTrainingSnapshot,
    experiment_dir: Path,
) -> RvcTrainingPreprocessResult:
    validation = _validate_preprocess_outputs(experiment_dir, snapshot)
    _validate_preprocess_manifest(experiment_dir, snapshot, validation)
    return RvcTrainingPreprocessResult(
        snapshot=snapshot,
        experiment_dir=experiment_dir,
        gt_wavs=_wav_files(experiment_dir / "0_gt_wavs"),
        wavs_16k=_wav_files(experiment_dir / "1_16k_wavs"),
        log_path=experiment_dir / "preprocess.log",
        successful_input_count=validation.successful_input_count,
        failed_inputs=validation.failed_inputs,
    )


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    root = layout.model_dir / "training" / "preprocess"
    return root / f".building-{uuid.uuid4().hex}"


def _write_preprocess_manifest(
    root: Path,
    snapshot: RvcTrainingSnapshot,
    validation: _PreprocessValidation,
) -> None:
    write_json_atomic(
        root / PREPROCESS_MANIFEST_NAME,
        {
            "version": PREPROCESS_MANIFEST_VERSION,
            "dataset_fingerprint": snapshot.fingerprint,
            "input_count": len(snapshot.inputs),
            "successful_input_count": validation.successful_input_count,
            "failed_inputs": [
                {
                    "input_name": failure.input_name,
                    "reason": failure.reason,
                    "source_item_id": failure.source_item_id,
                    "source_clip_id": failure.source_clip_id,
                }
                for failure in validation.failed_inputs
            ],
            "segment_count": len(_wav_files(root / "0_gt_wavs")),
        },
    )


def _validate_preprocess_manifest(
    root: Path,
    snapshot: RvcTrainingSnapshot,
    validation: _PreprocessValidation,
) -> None:
    path = root / PREPROCESS_MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingPreprocessError("RVC preprocess manifest cannot be read.") from exc
    version = data.get("version")
    if (
        version not in {1, 2, 3, PREPROCESS_MANIFEST_VERSION}
        or data.get("dataset_fingerprint") != snapshot.fingerprint
        or data.get("input_count") != len(snapshot.inputs)
        or data.get("segment_count") != len(_wav_files(root / "0_gt_wavs"))
    ):
        raise RvcTrainingPreprocessError("RVC preprocess outputs belong to a different dataset.")
    if version in {1, 2, 3}:
        # Legacy manifests used the RVC log rather than generated output pairs to count inputs.
        # Their files remain usable; current results are reconstructed from the actual outputs.
        return
    expected_failures = [
        {
            "input_name": failure.input_name,
            "reason": failure.reason,
            "source_item_id": failure.source_item_id,
            "source_clip_id": failure.source_clip_id,
        }
        for failure in validation.failed_inputs
    ]
    if (
        data.get("successful_input_count") != validation.successful_input_count
        or data.get("failed_inputs") != expected_failures
    ):
        raise RvcTrainingPreprocessError("RVC preprocess manifest does not match its outputs.")


def _classify_preprocess_outputs(
    log_text: str,
    snapshot: RvcTrainingSnapshot,
    produced_indices: frozenset[int],
) -> _PreprocessValidation:
    records: list[tuple[int, int, RvcTrainingSnapshotInput]] = []
    results: dict[int, str | None] = {item.order: None for item in snapshot.inputs}
    for item in snapshot.inputs:
        marker_match = _find_result_marker(log_text, item.path)
        if marker_match is not None:
            position, marker_length = marker_match
            records.append((position, marker_length, item))

    ordered = sorted(records, key=lambda record: record[0])
    for index, (position, marker_length, snapshot_input) in enumerate(ordered):
        result_start = position + marker_length
        result_end = ordered[index + 1][0] if index + 1 < len(ordered) else len(log_text)
        results[snapshot_input.order] = log_text[result_start:result_end].strip()

    failures: list[RvcTrainingPreprocessFailure] = []
    runtime_inputs = tuple(sorted(snapshot.inputs, key=lambda item: item.path.name.casefold()))
    for runtime_index, snapshot_input in enumerate(runtime_inputs):
        if runtime_index in produced_indices:
            continue
        result = results[snapshot_input.order]
        if result is None:
            reason = "No preprocessing result was recorded."
        elif result.startswith("Suc."):
            reason = "No usable audio segment was produced."
        else:
            reason = _preprocess_failure_reason(result)
        failures.append(
            _preprocess_failure(snapshot_input, reason)
        )
    failures.sort(key=lambda failure: failure.input_name.casefold())
    return _PreprocessValidation(len(produced_indices), tuple(failures))


def _produced_input_indices(
    output_paths: tuple[Path, ...],
    input_count: int,
) -> frozenset[int]:
    indices: set[int] = set()
    for path in output_paths:
        prefix, separator, _segment = path.stem.partition("_")
        if not separator or not prefix.isdecimal():
            raise RvcTrainingPreprocessError(
                f"RVC preprocessing created an unrecognized output name: {path.name}"
            )
        index = int(prefix)
        if index >= input_count:
            raise RvcTrainingPreprocessError(
                f"RVC preprocessing output does not match a training input: {path.name}"
            )
        indices.add(index)
    return frozenset(indices)


def _preprocess_failure(
    snapshot_input: RvcTrainingSnapshotInput,
    reason: str,
) -> RvcTrainingPreprocessFailure:
    return RvcTrainingPreprocessFailure(
        input_name=snapshot_input.path.name,
        reason=reason,
        source_item_id=snapshot_input.source_item_id,
        source_clip_id=snapshot_input.source_clip_id,
    )


def _find_result_marker(
    log_text: str,
    input_path: Path,
) -> tuple[int, int] | None:
    candidates = (str(input_path), input_path.as_posix(), input_path.name)
    matches: list[tuple[int, int]] = []
    for candidate in dict.fromkeys(candidates):
        marker = f"{candidate}->"
        position = log_text.find(marker)
        if position >= 0:
            matches.append((position, len(marker)))
    return min(matches, default=None, key=lambda match: match[0])


def _preprocess_failure_reason(result: str) -> str:
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.casefold() not in {"start preprocess", "end preprocess"}:
            return line[:1000]
    return "RVC rejected this training input without an error message."


def _preserve_failed_preprocess_log(
    staging: Path,
    layout: RvcModelPackageLayout,
) -> Path | None:
    source = staging / "preprocess.log"
    if not source.is_file():
        return None
    target = layout.model_dir / "training" / "diagnostics" / _FAILED_LOG_NAME
    try:
        return copy_file_atomic(source, target)
    except OSError:
        return None


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
