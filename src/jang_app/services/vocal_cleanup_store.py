from __future__ import annotations

import json
import shutil
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_EFFECTS,
    VOCAL_CLEANUP_STRENGTHS,
    VocalCleanupProject,
    VocalCleanupRegion,
    VocalCleanupResult,
)


VOCAL_CLEANUP_DIR = "cleanup"
VOCAL_CLEANUP_MANIFEST = "cleanup.json"
VOCAL_CLEANUP_SCHEMA = 1


class VocalCleanupStoreError(RuntimeError):
    pass


class VocalCleanupStore:
    def load(self, job_dir: Path, source_path: Path) -> VocalCleanupProject:
        root = _cleanup_root(job_dir)
        source = _require_source(source_path)
        manifest = root / VOCAL_CLEANUP_MANIFEST
        if not manifest.is_file():
            return VocalCleanupProject(source, _source_fingerprint(source))
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            project = _project_from_data(root, data)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VocalCleanupStoreError("The vocal cleanup project is damaged.") from exc
        if project.source_path != source or project.source_fingerprint != _source_fingerprint(source):
            return VocalCleanupProject(source, _source_fingerprint(source))
        return project

    def save(self, job_dir: Path, project: VocalCleanupProject) -> Path:
        root = _cleanup_root(job_dir)
        root.mkdir(parents=True, exist_ok=True)
        _validate_project(root, project)
        target = root / VOCAL_CLEANUP_MANIFEST
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
        _validate_range(start_ms, end_ms)
        _validate_effect(effect, strength)
        root = _cleanup_root(job_dir)
        region_id = replace_region_id or f"region-{uuid4().hex[:12]}"
        segment_root = root / "segments"
        segment_root.mkdir(parents=True, exist_ok=True)
        processed_target = segment_root / f"{region_id}-processed.wav"
        removed_target = segment_root / f"{region_id}-removed.wav"
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
        retained = tuple(item for item in project.regions if item.region_id != region_id)
        _ensure_non_overlapping(retained, region)
        _copy_file(processed_segment_path, processed_target)
        try:
            _copy_file(removed_segment_path, removed_target)
        except Exception:
            processed_target.unlink(missing_ok=True)
            raise
        updated = replace(
            project,
            regions=tuple(sorted((*retained, region), key=lambda item: item.start_ms)),
        )
        try:
            self.save(job_dir, updated)
        except Exception:
            processed_target.unlink(missing_ok=True)
            removed_target.unlink(missing_ok=True)
            raise
        processed_segment_path.unlink(missing_ok=True)
        removed_segment_path.unlink(missing_ok=True)
        return updated

    def remove_region(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        region_id: str,
    ) -> VocalCleanupProject:
        region = project.region(region_id)
        if region is None:
            return project
        updated = replace(
            project,
            regions=tuple(item for item in project.regions if item.region_id != region_id),
        )
        self.save(job_dir, updated)
        region.processed_segment_path.unlink(missing_ok=True)
        region.removed_segment_path.unlink(missing_ok=True)
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
        result_path = _require_managed_file(root / "results", path, "Cleanup result")
        result = VocalCleanupResult(
            result_id=f"cleanup-{uuid4().hex[:12]}",
            label=f"Clean vocal {len(project.results) + 1}",
            path=result_path,
            created_at=_now(),
        )
        updated = replace(project, results=(result, *project.results))
        self.save(job_dir, updated)
        return updated

    def remove_result(
        self,
        job_dir: Path,
        project: VocalCleanupProject,
        result_id: str,
    ) -> VocalCleanupProject:
        result = next((item for item in project.results if item.result_id == result_id), None)
        if result is None:
            return project
        updated = replace(
            project,
            results=tuple(item for item in project.results if item.result_id != result_id),
        )
        self.save(job_dir, updated)
        result.path.unlink(missing_ok=True)
        return updated


def _project_data(root: Path, project: VocalCleanupProject) -> dict[str, object]:
    return {
        "schema": VOCAL_CLEANUP_SCHEMA,
        "source_path": str(project.source_path),
        "source_fingerprint": project.source_fingerprint,
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
    if int(data.get("schema", 0)) != VOCAL_CLEANUP_SCHEMA:
        raise ValueError("Unsupported vocal cleanup schema")
    source_path = Path(str(data["source_path"])).expanduser().resolve()
    regions_data = data.get("regions", ())
    results_data = data.get("results", ())
    if not isinstance(regions_data, list) or not isinstance(results_data, list):
        raise TypeError("Invalid vocal cleanup collections")
    regions = tuple(_region_from_data(root, item) for item in regions_data)
    results = tuple(_result_from_data(root, item) for item in results_data)
    return VocalCleanupProject(
        source_path=source_path,
        source_fingerprint=str(data["source_fingerprint"]),
        regions=regions,
        results=results,
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
    _require_source(project.source_path)
    for region in project.regions:
        _validate_range(region.start_ms, region.end_ms)
        _validate_effect(region.effect, region.strength)
        _require_managed_file(root / "segments", region.processed_segment_path, "Processed segment")
        _require_managed_file(root / "segments", region.removed_segment_path, "Removed segment")
    for result in project.results:
        _require_managed_file(root / "results", result.path, "Cleanup result")
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
    return f"{size}:{modified_ns}:{file_sha256(Path(path))}"


def _require_source(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise VocalCleanupStoreError("The selected vocal file does not exist.")
    return source


def _require_managed_file(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise VocalCleanupStoreError(f"{label} is outside the managed cleanup folder.") from exc
    if not resolved.is_file():
        raise VocalCleanupStoreError(f"{label} is missing.")
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
    temporary = target.with_suffix(f"{target.suffix}.copying")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source, temporary)
        target.unlink(missing_ok=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
