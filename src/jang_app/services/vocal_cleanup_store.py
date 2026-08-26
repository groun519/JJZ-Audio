from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import numpy as np
import soundfile as sf

from jang_app.services.managed_files import (
    copy_file_atomic,
    file_sha256,
    managed_path_lock,
    write_json_atomic,
)
from jang_app.services.managed_transaction import (
    ManagedPathTransaction,
    ManagedTransactionError,
)
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_EFFECTS,
    VOCAL_CLEANUP_STRENGTHS,
    VocalCleanupProject,
    VocalCleanupRegion,
    VocalCleanupResult,
)


VOCAL_CLEANUP_DIR = "cleanup"
VOCAL_CLEANUP_MANIFEST = "cleanup.json"
VOCAL_CLEANUP_SCHEMA = 2
_LOGGER = logging.getLogger(__name__)
_RESULT_LABEL_PATTERN = re.compile(r"^Clean vocal (\d+)$")


class VocalCleanupStoreError(RuntimeError):
    pass


class VocalCleanupStore:
    def load(self, job_dir: Path, source_path: Path) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            return self._load_unlocked(root, source_path)

    def _load_unlocked(
        self,
        root: Path,
        source_path: Path,
    ) -> VocalCleanupProject:
        source = _require_source(source_path)
        manifest = root / VOCAL_CLEANUP_MANIFEST
        fingerprint = _source_fingerprint(source)
        if not manifest.is_file():
            return VocalCleanupProject(source, fingerprint)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            project = _project_from_data(root, data)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VocalCleanupStoreError("The vocal cleanup project is damaged.") from exc
        if project.source_path != source:
            raise VocalCleanupStoreError(
                "The cleanup project belongs to a different vocal source."
            )
        if not _fingerprints_match(project.source_fingerprint, fingerprint):
            raise VocalCleanupStoreError(
                "The source vocal changed after cleanup work was saved. "
                "Keep the existing project or reset it explicitly."
            )
        project = replace(project, source_fingerprint=fingerprint)
        _validate_project(root, project)
        return project

    def save(self, job_dir: Path, project: VocalCleanupProject) -> Path:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            return self._save_unlocked(root, project)

    def _save_unlocked(self, root: Path, project: VocalCleanupProject) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        _validate_project(root, project)
        target = _manifest_path(root)
        write_json_atomic(target, _project_data(root, project))
        return target

    def import_preview(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        *,
        start_ms: int,
        end_ms: int,
        effect: str,
        strength: str,
        processed_segment_path: Path,
        removed_segment_path: Path,
        replace_region_id: str = "",
    ) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            current = self._load_unlocked(root, project.source_path)
            _validate_range(start_ms, end_ms)
            _validate_effect(effect, strength)
            replaced = current.region(replace_region_id) if replace_region_id else None
            if replace_region_id and replaced is None:
                raise VocalCleanupStoreError(
                    "The cleanup region changed before this preview was applied."
                )
            _validate_preview_segments(
                current.source_path,
                start_ms,
                end_ms,
                processed_segment_path,
                removed_segment_path,
            )
            region_id = replace_region_id or f"region-{uuid4().hex[:12]}"
            generation = uuid4().hex[:12]
            segment_root = root / "segments"
            segment_root.mkdir(parents=True, exist_ok=True)
            processed_target = segment_root / f"{region_id}-{generation}-processed.wav"
            removed_target = segment_root / f"{region_id}-{generation}-removed.wav"
            region = VocalCleanupRegion(
                region_id=region_id,
                start_ms=start_ms,
                end_ms=end_ms,
                effect=effect,
                strength=strength,
                processed_segment_path=processed_target,
                removed_segment_path=removed_target,
                created_at=_now(),
            )
            retained = tuple(
                item for item in current.regions if item.region_id != region_id
            )
            _ensure_non_overlapping(retained, region)
            _copy_file(processed_segment_path, processed_target)
            try:
                _copy_file(removed_segment_path, removed_target)
            except Exception:
                processed_target.unlink(missing_ok=True)
                raise
            updated = replace(
                current,
                regions=tuple(sorted((*retained, region), key=lambda item: item.start_ms)),
            )
            transaction = ManagedPathTransaction(root, "replace-cleanup", region_id)
            try:
                if replaced is not None:
                    transaction.stage(
                        replaced.processed_segment_path,
                        "previous-processed.wav",
                    )
                    transaction.stage(
                        replaced.removed_segment_path,
                        "previous-removed.wav",
                    )
                self._save_unlocked(root, updated)
            except Exception as exc:
                processed_target.unlink(missing_ok=True)
                removed_target.unlink(missing_ok=True)
                _rollback_transaction(transaction, exc)
                raise
            _commit_transaction(transaction)
            _unlink_quietly(processed_segment_path)
            _unlink_quietly(removed_segment_path)
            return updated

    def remove_region(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        region_id: str,
    ) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            current = self._load_unlocked(root, project.source_path)
            region = current.region(region_id)
            if region is None:
                return current
            updated = replace(
                current,
                regions=tuple(
                    item for item in current.regions if item.region_id != region_id
                ),
            )
            transaction = ManagedPathTransaction(root, "delete-cleanup", region_id)
            try:
                transaction.stage(region.processed_segment_path, "processed.wav")
                transaction.stage(region.removed_segment_path, "removed.wav")
                self._save_unlocked(root, updated)
            except Exception as exc:
                _rollback_transaction(transaction, exc)
                raise
            _commit_transaction(transaction)
            return updated

    def create_result_path(self, job_dir: Path) -> Path:
        result_root = _cleanup_root(job_dir) / "results"
        result_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = result_root / f"vocals-clean-{stamp}.wav"
        suffix = 2
        while candidate.exists():
            candidate = result_root / f"vocals-clean-{stamp}-{suffix}.wav"
            suffix += 1
        return candidate

    def register_result(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        path: Path,
    ) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            current = self._load_unlocked(root, project.source_path)
            if current.regions != project.regions:
                raise VocalCleanupStoreError(
                    "Cleanup regions changed while the vocal was being rendered. "
                    "Create the cleaned vocal again."
                )
            result_path = _require_managed_file(
                root / "results",
                path,
                "Cleanup result",
            )
            number = max(1, current.next_result_number)
            result = VocalCleanupResult(
                result_id=f"cleanup-{uuid4().hex[:12]}",
                label=f"Clean vocal {number}",
                path=result_path,
                created_at=_now(),
            )
            updated = replace(
                current,
                results=(result, *current.results),
                next_result_number=number + 1,
            )
            self._save_unlocked(root, updated)
            return updated

    def remove_result(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        result_id: str,
    ) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        with managed_path_lock(_manifest_path(root)):
            current = self._load_unlocked(root, project.source_path)
            result = next(
                (item for item in current.results if item.result_id == result_id),
                None,
            )
            if result is None:
                return current
            updated = replace(
                current,
                results=tuple(
                    item for item in current.results if item.result_id != result_id
                ),
            )
            transaction = ManagedPathTransaction(root, "delete-result", result_id)
            try:
                transaction.stage(result.path, "result.wav")
                self._save_unlocked(root, updated)
            except Exception as exc:
                _rollback_transaction(transaction, exc)
                raise
            _commit_transaction(transaction)
            return updated


def _project_data(root: Path, project: VocalCleanupProject) -> dict[str, object]:
    return {
        "schema": VOCAL_CLEANUP_SCHEMA,
        "source_path": str(project.source_path),
        "source_fingerprint": project.source_fingerprint,
        "next_result_number": project.next_result_number,
        "regions": [
            {
                **asdict(region),
                "processed_segment_path": str(region.processed_segment_path.relative_to(root)),
                "removed_segment_path": str(region.removed_segment_path.relative_to(root)),
            }
            for region in project.regions
        ],
        "results": [
            {
                **asdict(result),
                "path": str(result.path.relative_to(root)),
            }
            for result in project.results
        ],
    }


def _project_from_data(root: Path, data: Mapping[str, object]) -> VocalCleanupProject:
    schema = int(data.get("schema", 0))
    if schema not in {1, VOCAL_CLEANUP_SCHEMA}:
        raise ValueError("Unsupported vocal cleanup schema")
    source_path = Path(str(data["source_path"])).expanduser().resolve()
    regions_data = data.get("regions", ())
    results_data = data.get("results", ())
    if not isinstance(regions_data, list) or not isinstance(results_data, list):
        raise TypeError("Invalid vocal cleanup collections")
    regions = tuple(_region_from_data(root, item) for item in regions_data)
    results = tuple(_result_from_data(root, item) for item in results_data)
    next_result_number = int(
        data.get("next_result_number", _next_result_number(results))
    )
    if next_result_number < 1:
        raise ValueError("Invalid cleanup result sequence")
    return VocalCleanupProject(
        source_path=source_path,
        source_fingerprint=str(data["source_fingerprint"]),
        regions=regions,
        results=results,
        next_result_number=next_result_number,
    )


def _region_from_data(root: Path, value: object) -> VocalCleanupRegion:
    if not isinstance(value, Mapping):
        raise TypeError("Invalid vocal cleanup region")
    region = VocalCleanupRegion(
        region_id=str(value["region_id"]),
        start_ms=int(value["start_ms"]),
        end_ms=int(value["end_ms"]),
        effect=str(value["effect"]),
        strength=str(value["strength"]),
        processed_segment_path=_managed_path(root, value["processed_segment_path"]),
        removed_segment_path=_managed_path(root, value["removed_segment_path"]),
        created_at=str(value["created_at"]),
    )
    _validate_range(region.start_ms, region.end_ms)
    _validate_effect(region.effect, region.strength)
    return region


def _result_from_data(root: Path, value: object) -> VocalCleanupResult:
    if not isinstance(value, Mapping):
        raise TypeError("Invalid vocal cleanup result")
    return VocalCleanupResult(
        result_id=str(value["result_id"]),
        label=str(value["label"]),
        path=_managed_path(root, value["path"]),
        created_at=str(value["created_at"]),
    )


def _validate_project(root: Path, project: VocalCleanupProject) -> None:
    source = _require_source(project.source_path)
    source_info = _audio_info(source, "Source vocal")
    for region in project.regions:
        _validate_range(region.start_ms, region.end_ms)
        _validate_effect(region.effect, region.strength)
        _validate_managed_segment(root, source_info, region)
    for result in project.results:
        _require_managed_path(root / "results", result.path, "Cleanup result")
    ordered = tuple(sorted(project.regions, key=lambda item: item.start_ms))
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_ms < previous.end_ms:
            raise VocalCleanupStoreError("Vocal cleanup regions cannot overlap.")


def _ensure_non_overlapping(
    regions: tuple[VocalCleanupRegion, ...],
    candidate: VocalCleanupRegion,
) -> None:
    if any(
        candidate.start_ms < region.end_ms and region.start_ms < candidate.end_ms
        for region in regions
    ):
        raise VocalCleanupStoreError("The selected range overlaps another cleanup region.")


def _validate_range(start_ms: int, end_ms: int) -> None:
    if start_ms < 0 or end_ms - start_ms < 250:
        raise VocalCleanupStoreError("Select at least 0.25 seconds of vocal audio.")


def _validate_effect(effect: str, strength: str) -> None:
    if effect not in VOCAL_CLEANUP_EFFECTS:
        raise VocalCleanupStoreError(f"Unsupported vocal cleanup effect: {effect}")
    if strength not in VOCAL_CLEANUP_STRENGTHS:
        raise VocalCleanupStoreError(f"Unsupported vocal cleanup strength: {strength}")


def _cleanup_root(job_dir: Path) -> Path:
    return job_dir.expanduser().resolve() / VOCAL_CLEANUP_DIR


def _source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return _cached_source_fingerprint(str(path), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=128)
def _cached_source_fingerprint(path: str, size: int, modified_ns: int) -> str:
    del modified_ns
    return f"{size}:{file_sha256(Path(path))}"


def _fingerprints_match(stored: str, current: str) -> bool:
    stored_parts = stored.split(":")
    current_parts = current.split(":")
    if len(stored_parts) not in {2, 3} or len(current_parts) != 2:
        return False
    return (
        stored_parts[0] == current_parts[0]
        and stored_parts[-1].casefold() == current_parts[-1].casefold()
    )


def _require_source(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise VocalCleanupStoreError("The selected vocal file does not exist.")
    return source


def _require_managed_file(root: Path, path: Path, label: str) -> Path:
    resolved = _require_managed_path(root, path, label)
    if not resolved.is_file():
        raise VocalCleanupStoreError(f"{label} is missing.")
    return resolved


def _require_managed_path(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise VocalCleanupStoreError(
            f"{label} is outside the managed cleanup folder."
        ) from exc
    return resolved


def _managed_path(root: Path, value: object) -> Path:
    candidate = (root / str(value)).expanduser().resolve()
    try:
        candidate.relative_to(root.expanduser().resolve())
    except ValueError as exc:
        raise ValueError("Managed cleanup path escapes its folder") from exc
    return candidate


def _copy_file(source: Path, target: Path) -> None:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise VocalCleanupStoreError("The cleanup preview is missing.")
    copy_file_atomic(source, target)


def _manifest_path(root: Path) -> Path:
    return root / VOCAL_CLEANUP_MANIFEST


def _next_result_number(results: tuple[VocalCleanupResult, ...]) -> int:
    numbers = []
    for result in results:
        match = _RESULT_LABEL_PATTERN.match(result.label)
        if match is not None:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _validate_preview_segments(
    source_path: Path,
    start_ms: int,
    end_ms: int,
    processed_path: Path,
    removed_path: Path,
) -> None:
    source_info = _audio_info(source_path, "Source vocal")
    _validate_segment_audio(
        processed_path,
        source_info,
        start_ms,
        end_ms,
        "Processed segment",
    )
    _validate_segment_audio(
        removed_path,
        source_info,
        start_ms,
        end_ms,
        "Removed segment",
    )


def _validate_managed_segment(root: Path, source_info, region: VocalCleanupRegion) -> None:
    processed = _require_managed_file(
        root / "segments",
        region.processed_segment_path,
        "Processed segment",
    )
    removed = _require_managed_file(
        root / "segments",
        region.removed_segment_path,
        "Removed segment",
    )
    _validate_segment_audio(
        processed,
        source_info,
        region.start_ms,
        region.end_ms,
        "Processed segment",
    )
    _validate_segment_audio(
        removed,
        source_info,
        region.start_ms,
        region.end_ms,
        "Removed segment",
    )


def _audio_info(path: Path, label: str):
    try:
        return sf.info(str(path))
    except (OSError, RuntimeError) as exc:
        raise VocalCleanupStoreError(f"{label} is not readable audio.") from exc


def _validate_segment_audio(
    path: Path,
    source_info,
    start_ms: int,
    end_ms: int,
    label: str,
) -> None:
    segment = path.expanduser().resolve()
    info = _audio_info(segment, label)
    expected_frames = round((end_ms - start_ms) * source_info.samplerate / 1000)
    tolerance = max(4, math.ceil(source_info.samplerate * 0.002))
    if info.samplerate != source_info.samplerate or info.channels != source_info.channels:
        raise VocalCleanupStoreError(
            f"{label} format does not match the source vocal."
        )
    if abs(info.frames - expected_frames) > tolerance:
        raise VocalCleanupStoreError(
            f"{label} duration does not match the selected range."
        )
    try:
        blocks = sf.blocks(str(segment), blocksize=65_536, dtype="float32", always_2d=True)
        if any(not np.isfinite(block).all() for block in blocks):
            raise VocalCleanupStoreError(f"{label} contains invalid audio samples.")
    except VocalCleanupStoreError:
        raise
    except (OSError, RuntimeError) as exc:
        raise VocalCleanupStoreError(f"{label} is not readable audio.") from exc


def _rollback_transaction(
    transaction: ManagedPathTransaction,
    original_error: Exception,
) -> None:
    try:
        transaction.rollback()
    except ManagedTransactionError as rollback_error:
        raise VocalCleanupStoreError(
            f"Cleanup update failed and rollback also failed: {rollback_error}"
        ) from original_error


def _commit_transaction(transaction: ManagedPathTransaction) -> None:
    try:
        transaction.mark_committed()
    except OSError as exc:
        _LOGGER.warning(
            "Could not mark cleanup transaction %s committed: %s",
            transaction.transaction_id,
            exc,
        )
    if not transaction.purge():
        _LOGGER.warning(
            "Committed cleanup transaction removal was deferred: %s",
            transaction.folder,
        )


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _LOGGER.warning("Could not remove committed cleanup preview file %s: %s", path, exc)


def _now() -> str:
    return datetime.now(UTC).isoformat()
