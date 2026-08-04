from __future__ import annotations

import json
import re
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
)
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_artifacts import (
    publish_training_outputs,
    remove_training_staging,
)
from jang_app.services.rvc_training_control import RvcTrainingCancelled
from jang_app.services.rvc_training_extract import RvcTrainingExtractResult, load_rvc_extract_result
from jang_app.services.rvc_training_runtime import inspect_rvc_training_runtime
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


INDEX_MANIFEST_NAME = "jjzero_index.json"
TOTAL_FEATURES_NAME = "total_fea.npy"
_PROGRESS_PATTERN = re.compile(r"^JJZERO_INDEX_PROGRESS=(?P<progress>\d+)$")


class RvcTrainingIndexError(RuntimeError):
    """Raised when an RVC FAISS feature index cannot be built or verified."""


@dataclass(frozen=True)
class RvcTrainingIndexResult:
    experiment_dir: Path
    trained_index: Path
    added_index: Path
    total_features: Path
    dataset_fingerprint: str
    feature_count: int
    source_vector_count: int
    indexed_vector_count: int


def build_rvc_training_index(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    *,
    cancellation: CommandCancellation | None = None,
    progress: Callable[[int], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
    command_runner: Callable[..., CommandResult] = run_cancellable_command,
) -> RvcTrainingIndexResult:
    runtime = runtime_root.expanduser().resolve()
    inspection = inspect_rvc_training_runtime(runtime)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingIndexError(f"RVC training runtime is incomplete: {missing}")
    extract = load_rvc_extract_result(model_id, layout)
    worker = _artifact_worker_path()
    if not worker.is_file():
        raise RvcTrainingIndexError(f"RVC artifact worker is missing: {worker}")

    token = cancellation or CommandCancellation()
    state_store = RvcTrainingStateStore(model_id, layout)
    state_store.update_phase(RvcTrainingPhase.INDEX)
    staging = _staging_dir(layout)
    staging.parent.mkdir(parents=True, exist_ok=True)
    logger = get_logger()
    _report(progress, 0)

    def handle_output(line: str) -> None:
        match = _PROGRESS_PATTERN.fullmatch(line.strip())
        if match is not None:
            _report(progress, int(match.group("progress")))
        if output_callback is not None:
            output_callback(line)

    try:
        completed = command_runner(
            [
                str(runtime / "runtime" / "python.exe"),
                str(worker),
                "build-index",
                str(layout.experiment_dir / "3_feature768"),
                str(staging),
                layout.rvc_name,
            ],
            cwd=layout.root,
            env=build_rvc_environment(runtime),
            output_callback=handle_output,
            cancellation=token,
        )
        if completed.cancelled or token.is_requested:
            raise RvcTrainingCancelled("RVC index generation was stopped.")
        if completed.returncode != 0:
            raise RvcTrainingIndexError(
                f"RVC index generation failed with exit code {completed.returncode}: {completed.output}"
            )
        report = _last_json_object(completed.output)
        fingerprint = state_store.load().dataset_fingerprint
        result = _validate_index_outputs(staging, report, extract, fingerprint)
        write_json_atomic(staging / INDEX_MANIFEST_NAME, _index_manifest(result))
        publish_training_outputs(
            staging,
            layout.experiment_dir,
            (
                result.total_features.name,
                result.trained_index.name,
                result.added_index.name,
                INDEX_MANIFEST_NAME,
            ),
            backup_label="index",
        )
        published = load_rvc_training_index(model_id, layout)
        state_store.update_phase(RvcTrainingPhase.INDEX_READY)
        _report(progress, 100)
        logger.info("RVC index ready: model=%s vectors=%s", model_id, published.indexed_vector_count)
        return published
    except RvcTrainingCancelled:
        state_store.update_phase(RvcTrainingPhase.STOPPED)
        raise
    except Exception as exc:
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=str(exc))
        logger.error("RVC index generation failed: model=%s error=%s", model_id, exc)
        if isinstance(exc, RvcTrainingIndexError):
            raise
        raise RvcTrainingIndexError(str(exc)) from exc
    finally:
        remove_training_staging(staging, layout.model_dir)


def load_rvc_training_index(
    model_id: str,
    layout: RvcModelPackageLayout,
) -> RvcTrainingIndexResult:
    extract = load_rvc_extract_result(model_id, layout)
    path = layout.experiment_dir / INDEX_MANIFEST_NAME
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingIndexError("RVC index manifest cannot be read.") from exc
    if not isinstance(report, dict) or report.get("version") != 1:
        raise RvcTrainingIndexError("RVC index manifest is invalid.")
    fingerprint = RvcTrainingStateStore(model_id, layout).load().dataset_fingerprint
    result = _validate_index_outputs(layout.experiment_dir, report, extract, fingerprint)
    hashes = report.get("sha256")
    if not isinstance(hashes, dict) or any(
        hashes.get(path.name) != file_sha256(path)
        for path in (result.total_features, result.trained_index, result.added_index)
    ):
        raise RvcTrainingIndexError("RVC index files were modified after generation.")
    return result


def _validate_index_outputs(
    root: Path,
    report: dict[str, object],
    extract: RvcTrainingExtractResult,
    fingerprint: str,
) -> RvcTrainingIndexResult:
    if report.get("version") != 1 or report.get("dataset_fingerprint", fingerprint) != fingerprint:
        raise RvcTrainingIndexError("RVC index belongs to a different dataset.")
    names = tuple(_safe_output_name(report.get(key)) for key in (
        "trained_index",
        "added_index",
        "total_features",
    ))
    trained, added, total = (root / name for name in names)
    if not all(path.is_file() and path.stat().st_size > 0 for path in (trained, added, total)):
        raise RvcTrainingIndexError("RVC index generation did not create every output file.")
    expected_vectors = sum(_feature_rows(path) for path in extract.feature_files)
    indexed_vectors = 10000 if expected_vectors > 200000 else expected_vectors
    if (
        report.get("dimension") != 768
        or report.get("feature_count") != len(extract.feature_files)
        or report.get("source_vector_count") != expected_vectors
        or report.get("vector_count") != indexed_vectors
    ):
        raise RvcTrainingIndexError("RVC index report does not match extracted features.")
    try:
        array = np.load(total, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RvcTrainingIndexError("RVC combined feature array cannot be read.") from exc
    if array.shape != (indexed_vectors, 768) or not np.isfinite(array).all():
        raise RvcTrainingIndexError("RVC combined feature array is invalid.")
    return RvcTrainingIndexResult(
        experiment_dir=root,
        trained_index=trained,
        added_index=added,
        total_features=total,
        dataset_fingerprint=fingerprint,
        feature_count=len(extract.feature_files),
        source_vector_count=expected_vectors,
        indexed_vector_count=indexed_vectors,
    )


def _index_manifest(result: RvcTrainingIndexResult) -> dict[str, object]:
    paths = (result.total_features, result.trained_index, result.added_index)
    return {
        "version": 1,
        "dataset_fingerprint": result.dataset_fingerprint,
        "feature_count": result.feature_count,
        "source_vector_count": result.source_vector_count,
        "vector_count": result.indexed_vector_count,
        "dimension": 768,
        "trained_index": result.trained_index.name,
        "added_index": result.added_index.name,
        "total_features": result.total_features.name,
        "sha256": {path.name: file_sha256(path) for path in paths},
    }


def _last_json_object(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RvcTrainingIndexError("RVC index worker did not return a report.")


def _safe_output_name(value: object) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise RvcTrainingIndexError("RVC index report contains an unsafe output name.")
    return value


def _feature_rows(path: Path) -> int:
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RvcTrainingIndexError(f"RVC feature array cannot be read: {path}") from exc
    if array.ndim != 2 or array.shape[1] != 768 or array.shape[0] <= 0:
        raise RvcTrainingIndexError(f"RVC feature array shape is invalid: {path}")
    return int(array.shape[0])


def _artifact_worker_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rvc_tools" / "rvc_artifact_worker.py"


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    return layout.model_dir / "training" / "index" / f".building-{uuid.uuid4().hex}"


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, int(value))))
