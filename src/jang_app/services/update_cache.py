from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic


UPDATE_CLEANUP_MARKER = ".cleanup-ready.json"
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpdateCacheCleanupReport:
    removed_files: int = 0
    reclaimed_bytes: int = 0
    failed_paths: tuple[Path, ...] = ()

    def merged(self, other: UpdateCacheCleanupReport) -> UpdateCacheCleanupReport:
        return UpdateCacheCleanupReport(
            self.removed_files + other.removed_files,
            self.reclaimed_bytes + other.reclaimed_bytes,
            self.failed_paths + other.failed_paths,
        )


def mark_update_cleanup_ready(
    cache_root: Path,
    update_dir: Path,
    target_version: str,
) -> bool:
    managed = _managed_update_dir(cache_root, update_dir)
    if managed is None or _version_tuple(target_version) is None:
        return False
    try:
        write_json_atomic(
            managed / UPDATE_CLEANUP_MARKER,
            {"schema_version": 1, "target_version": target_version},
        )
    except OSError:
        return False
    return True


def discard_completed_update(
    cache_root: Path,
    update_dir: Path,
) -> UpdateCacheCleanupReport:
    managed = _managed_update_dir(cache_root, update_dir)
    if managed is None:
        return UpdateCacheCleanupReport()
    return _remove_update_directory(managed)


def cleanup_completed_updates(
    cache_root: Path,
    current_version: str,
) -> UpdateCacheCleanupReport:
    current = _version_tuple(current_version)
    updates_root = _updates_root(cache_root)
    if current is None or not updates_root.is_dir():
        return UpdateCacheCleanupReport()
    report = UpdateCacheCleanupReport()
    try:
        candidates = tuple(updates_root.iterdir())
    except OSError:
        return report
    for candidate in candidates:
        managed = _managed_update_dir(cache_root, candidate)
        if managed is None:
            continue
        target = _marker_target(managed / UPDATE_CLEANUP_MARKER)
        if target is None or current < target:
            continue
        report = report.merged(_remove_update_directory(managed))
    return report


def _updates_root(cache_root: Path) -> Path:
    return (cache_root.expanduser().resolve() / "updates").resolve()


def _managed_update_dir(cache_root: Path, update_dir: Path) -> Path | None:
    updates_root = _updates_root(cache_root)
    source = update_dir.expanduser()
    try:
        if source.is_symlink():
            return None
        candidate = source.resolve()
    except OSError:
        return None
    if candidate.parent != updates_root or not candidate.is_dir():
        return None
    return candidate


def _marker_target(marker: Path) -> tuple[int, int, int] | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return None
    return _version_tuple(str(data.get("target_version", "")))


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.fullmatch(value.strip())
    return tuple(int(part) for part in match.groups()) if match is not None else None


def _remove_update_directory(root: Path) -> UpdateCacheCleanupReport:
    marker = root / UPDATE_CLEANUP_MARKER
    removed, reclaimed, failures = _remove_children(root, marker)
    if failures:
        return UpdateCacheCleanupReport(removed, reclaimed, tuple(failures))
    if marker.is_file():
        size = _file_size(marker)
        try:
            marker.unlink()
        except OSError:
            return UpdateCacheCleanupReport(removed, reclaimed, (marker.resolve(),))
        removed += 1
        reclaimed += size
    try:
        root.rmdir()
    except OSError:
        return UpdateCacheCleanupReport(removed, reclaimed, (root.resolve(),))
    return UpdateCacheCleanupReport(removed, reclaimed)


def _remove_children(
    directory: Path,
    marker: Path,
) -> tuple[int, int, list[Path]]:
    removed = 0
    reclaimed = 0
    failures: list[Path] = []
    try:
        children = tuple(directory.iterdir())
    except OSError:
        return 0, 0, [directory.resolve()]
    for child in children:
        if child == marker:
            continue
        if _is_reparse_point(child) or not child.is_dir():
            size = _file_size(child)
            try:
                _remove_leaf(child)
            except OSError:
                failures.append(child.resolve())
            else:
                removed += 1
                reclaimed += size
            continue
        child_removed, child_reclaimed, child_failures = _remove_children(child, marker)
        removed += child_removed
        reclaimed += child_reclaimed
        failures.extend(child_failures)
        if child_failures:
            continue
        try:
            child.rmdir()
        except OSError:
            failures.append(child.resolve())
    return removed, reclaimed, failures


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _remove_leaf(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        os.rmdir(path)
    else:
        path.unlink()


def _file_size(path: Path) -> int:
    try:
        return path.lstat().st_size
    except OSError:
        return 0
