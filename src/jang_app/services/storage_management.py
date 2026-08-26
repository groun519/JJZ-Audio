from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import uuid4

from jang_app.services.app_paths import AppPaths
from jang_app.services.separation_recipe import SEPARATION_RUN_MANIFEST
from jang_app.services.song_package import VOCAL_STAGE
from jang_app.services.update_cache import UPDATE_CLEANUP_MARKER
from jang_app.version import __version__


@dataclass(frozen=True)
class StorageCategory:
    key: str
    title: str
    safety: str
    size_bytes: int
    file_count: int
    paths: tuple[Path, ...]
    errors: tuple[Path, ...] = ()


@dataclass(frozen=True)
class StorageInventory:
    storage_root: Path
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    categories: tuple[StorageCategory, ...]
    checked_at: datetime

    @property
    def managed_bytes(self) -> int:
        return sum(category.size_bytes for category in self.categories)


@dataclass(frozen=True)
class CleanupCandidate:
    category: str
    path: Path
    allowed_root: Path
    size_bytes: int
    file_count: int
    requires_idle: bool = False
    quarantined: bool = False


@dataclass(frozen=True)
class StorageCleanupPlan:
    candidates: tuple[CleanupCandidate, ...]
    skipped_for_active_jobs: bool = False

    @property
    def reclaimable_bytes(self) -> int:
        return sum(candidate.size_bytes for candidate in self.candidates)

    @property
    def file_count(self) -> int:
        return sum(candidate.file_count for candidate in self.candidates)


@dataclass(frozen=True)
class StorageCleanupReport:
    removed_files: int
    reclaimed_bytes: int
    failed_paths: tuple[Path, ...]
    skipped_paths: tuple[Path, ...] = ()


def scan_storage(
    paths: AppPaths,
    progress=None,
) -> StorageInventory:
    specifications = _category_specifications(paths)
    categories: list[StorageCategory] = []
    total_steps = max(1, len(specifications))
    for index, (key, title, safety, roots, exclusions) in enumerate(specifications):
        size, count, errors = _measure_roots(roots, exclusions)
        categories.append(
            StorageCategory(key, title, safety, size, count, roots, errors)
        )
        if progress is not None:
            progress(round((index + 1) * 100 / total_steps))
    disk_root = _existing_ancestor(paths.storage_root)
    try:
        usage = shutil.disk_usage(disk_root)
        total_bytes, used_bytes, free_bytes = usage.total, usage.used, usage.free
    except OSError:
        total_bytes = used_bytes = free_bytes = 0
    return StorageInventory(
        paths.storage_root,
        total_bytes,
        used_bytes,
        free_bytes,
        tuple(categories),
        datetime.now(UTC),
    )


def build_safe_cleanup_plan(
    paths: AppPaths,
    *,
    active_jobs: bool = False,
    now: datetime | None = None,
) -> StorageCleanupPlan:
    current = now or datetime.now(UTC)
    candidates: list[CleanupCandidate] = []
    if not active_jobs:
        transient_roots = (
            (paths.cache_dir / "jobs", "Temporary jobs"),
            (paths.cache_dir / "pitch-analysis", "Analysis cache"),
            (paths.cache_dir / "drive_downloads", "Drive downloads"),
            (paths.cache_dir / "model_shares", "Model share cache"),
            (paths.cache_dir / "model_work_shares", "Model work share cache"),
            (paths.workspace_root / "playback", "Playback cache"),
            (paths.workspace_root / "previews", "Preview cache"),
        )
        for root, category in transient_roots:
            candidates.extend(
                _quarantine_candidates(root, requires_idle=True)
            )
            candidates.extend(
                _child_candidates(root, category, requires_idle=True)
            )
        candidates.extend(
            _library_transient_candidates(paths.workspace_root / "library" / "songs")
        )
        candidates.extend(_completed_update_candidates(paths.cache_dir))

    diagnostic_cutoff = current - timedelta(days=7)
    candidates.extend(
        _matching_file_candidates(
            paths.log_dir,
            ("JJZero-Support-Diagnostics-*.zip",),
            "Generated diagnostics",
            diagnostic_cutoff,
        )
    )
    candidates.extend(
        _matching_file_candidates(
            paths.log_dir / "jobs",
            ("JJZero-Training-Diagnostics-*.zip",),
            "Generated diagnostics",
            diagnostic_cutoff,
            recursive=True,
        )
    )
    log_cutoff = current - timedelta(days=14)
    candidates.extend(
        _matching_file_candidates(
            paths.log_dir,
            ("jang.log.*",),
            "Old application logs",
            log_cutoff,
        )
    )
    unique = {candidate.path.resolve(): candidate for candidate in candidates}
    return StorageCleanupPlan(tuple(unique.values()), active_jobs)


def execute_cleanup(
    plan: StorageCleanupPlan,
    progress=None,
    *,
    active_jobs: Callable[[], bool] | None = None,
    idle_guard: Callable[[Callable[[], None]], bool] | None = None,
) -> StorageCleanupReport:
    removed = 0
    reclaimed = 0
    failures: list[Path] = []
    skipped: list[Path] = []
    total = max(1, len(plan.candidates))
    for index, candidate in enumerate(plan.candidates):
        if candidate.requires_idle and active_jobs is not None and active_jobs():
            skipped.append(candidate.path)
            if progress is not None:
                progress(round((index + 1) * 100 / total))
            continue
        if not _candidate_is_safe(candidate):
            failures.append(candidate.path)
            continue
        quarantine = (
            candidate.path.parent
            if candidate.quarantined
            else candidate.path.parent / ".jjzero-cleanup"
        )
        staged = candidate.path
        moved = False
        try:
            if not candidate.quarantined:
                quarantine.mkdir(parents=True, exist_ok=True)
                staged = quarantine / f"{uuid4().hex}-{candidate.path.name}"
                move = lambda: os.replace(candidate.path, staged)
                if (
                    candidate.requires_idle
                    and idle_guard is not None
                    and not idle_guard(move)
                ):
                    skipped.append(candidate.path)
                    try:
                        quarantine.rmdir()
                    except OSError:
                        pass
                    if progress is not None:
                        progress(round((index + 1) * 100 / total))
                    continue
                if not candidate.requires_idle or idle_guard is None:
                    move()
                moved = True
            _remove_path(staged)
            removed += candidate.file_count
            reclaimed += candidate.size_bytes
        except OSError:
            if moved and _restore_staged_candidate(staged, candidate.path):
                failures.append(candidate.path)
            else:
                failures.append(staged if staged.exists() else candidate.path)
        try:
            quarantine.rmdir()
        except OSError:
            pass
        if progress is not None:
            progress(round((index + 1) * 100 / total))
    return StorageCleanupReport(
        removed,
        reclaimed,
        tuple(failures),
        tuple(skipped),
    )


def _category_specifications(paths: AppPaths):
    workspace = paths.workspace_root
    cache = paths.cache_dir
    workspace_exclusions = (
        workspace / "library",
        workspace / "models",
        workspace / "rvc_cli",
        workspace / "playback",
        workspace / "previews",
    )
    cache_exclusions = (cache / "separation",)
    return (
        ("library", "Library", "protected", (workspace / "library",), ()),
        (
            "models",
            "Models and training work",
            "protected",
            (workspace / "models", workspace / "rvc_cli"),
            (),
        ),
        ("exports", "Exports", "managed", (paths.output_root,), ()),
        (
            "ai_assets",
            "Downloaded AI assets",
            "downloadable",
            (cache / "separation",),
            (),
        ),
        (
            "cache",
            "Cache and temporary files",
            "safe",
            (cache, workspace / "playback", workspace / "previews"),
            cache_exclusions,
        ),
        ("logs", "Logs and diagnostics", "safe", (paths.log_dir,), ()),
        ("runtime", "Audio runtime", "protected", (paths.runtime_root,), ()),
        (
            "workspace_other",
            "Other workspace data",
            "protected",
            (workspace,),
            workspace_exclusions,
        ),
    )


def _measure_roots(
    roots: tuple[Path, ...],
    exclusions: tuple[Path, ...],
) -> tuple[int, int, tuple[Path, ...]]:
    size = 0
    count = 0
    errors: list[Path] = []
    resolved_exclusions = tuple(_safe_resolve(path) for path in exclusions)
    for root in _deduplicated_roots(roots):
        measured_size, measured_count, measured_errors = _measure_path(
            root,
            resolved_exclusions,
        )
        size += measured_size
        count += measured_count
        errors.extend(measured_errors)
    return size, count, tuple(errors)


def _measure_path(
    root: Path,
    exclusions: tuple[Path, ...] = (),
) -> tuple[int, int, list[Path]]:
    if not root.exists() or _is_reparse(root):
        return 0, 0, []
    if root.is_file():
        return _file_size(root), 1, []
    size = 0
    count = 0
    errors: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        resolved = _safe_resolve(current)
        if resolved in exclusions:
            continue
        try:
            entries = tuple(os.scandir(current))
        except OSError:
            errors.append(current)
            continue
        for entry in entries:
            path = Path(entry.path)
            if _safe_resolve(path) in exclusions:
                continue
            try:
                if entry.is_symlink() or _is_reparse(path):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    size += entry.stat(follow_symlinks=False).st_size
                    count += 1
            except OSError:
                errors.append(path)
    return size, count, errors


def _deduplicated_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved = sorted({_safe_resolve(path) for path in roots}, key=lambda path: len(path.parts))
    selected: list[Path] = []
    for path in resolved:
        if any(path == parent or path.is_relative_to(parent) for parent in selected):
            continue
        selected.append(path)
    return tuple(selected)


def _child_candidates(
    root: Path,
    category: str,
    *,
    requires_idle: bool = False,
) -> list[CleanupCandidate]:
    try:
        children = tuple(root.iterdir()) if root.is_dir() else ()
    except OSError:
        return []
    candidates: list[CleanupCandidate] = []
    for child in children:
        if child.name == ".jjzero-cleanup" or _is_reparse(child):
            continue
        size, count, _errors = _measure_path(child)
        candidates.append(
            CleanupCandidate(
                category,
                child,
                root,
                size,
                count,
                requires_idle=requires_idle,
            )
        )
    return candidates


def _quarantine_candidates(
    root: Path,
    *,
    requires_idle: bool,
) -> list[CleanupCandidate]:
    quarantine = root / ".jjzero-cleanup"
    try:
        children = tuple(quarantine.iterdir()) if quarantine.is_dir() else ()
    except OSError:
        return []
    candidates: list[CleanupCandidate] = []
    for child in children:
        if _is_reparse(child):
            continue
        size, count, _errors = _measure_path(child)
        candidates.append(
            CleanupCandidate(
                "Interrupted cleanup",
                child,
                quarantine,
                size,
                count,
                requires_idle=requires_idle,
                quarantined=True,
            )
        )
    return candidates


def _library_transient_candidates(songs_root: Path) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    try:
        song_folders = tuple(songs_root.iterdir()) if songs_root.is_dir() else ()
    except OSError:
        return candidates
    for song_folder in song_folders:
        if not song_folder.is_dir() or _is_reparse(song_folder):
            continue
        separations = song_folder / VOCAL_STAGE / "separations"
        try:
            runs = tuple(separations.iterdir()) if separations.is_dir() else ()
        except OSError:
            continue
        for run in runs:
            if not run.is_dir() or _is_reparse(run):
                continue
            if run.name.startswith("r_") and not (run / SEPARATION_RUN_MANIFEST).is_file():
                size, count, _errors = _measure_path(run)
                candidates.append(
                    CleanupCandidate(
                        "Interrupted separation",
                        run,
                        separations,
                        size,
                        count,
                        requires_idle=True,
                    )
                )
                continue
            preview_root = run / "cleanup" / ".preview"
            candidates.extend(
                _child_candidates(
                    preview_root,
                    "Interrupted vocal cleanup previews",
                    requires_idle=True,
                )
            )
    return candidates


def _restore_staged_candidate(staged: Path, original: Path) -> bool:
    if not staged.exists() or original.exists():
        return False
    try:
        os.replace(staged, original)
    except OSError:
        return False
    return True


def _completed_update_candidates(cache_root: Path) -> list[CleanupCandidate]:
    updates = cache_root / "updates"
    try:
        children = tuple(updates.iterdir()) if updates.is_dir() else ()
    except OSError:
        return []
    current = _version_tuple(__version__)
    candidates: list[CleanupCandidate] = []
    for child in children:
        marker = child / UPDATE_CLEANUP_MARKER
        target = _cleanup_marker_version(marker)
        if current is None or target is None or current < target or _is_reparse(child):
            continue
        size, count, _errors = _measure_path(child)
        candidates.append(CleanupCandidate("Completed updates", child, updates, size, count))
    return candidates


def _matching_file_candidates(
    root: Path,
    patterns: tuple[str, ...],
    category: str,
    cutoff: datetime,
    *,
    recursive: bool = False,
) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    for pattern in patterns:
        try:
            matches = root.rglob(pattern) if recursive else root.glob(pattern)
            paths = tuple(matches)
        except OSError:
            continue
        for path in paths:
            if not path.is_file() or _is_reparse(path):
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                continue
            if modified > cutoff:
                continue
            candidates.append(
                CleanupCandidate(category, path, root, _file_size(path), 1)
            )
    return candidates


def _candidate_is_safe(candidate: CleanupCandidate) -> bool:
    path = _safe_resolve(candidate.path)
    root = _safe_resolve(candidate.allowed_root)
    return (
        path != root
        and path.is_relative_to(root)
        and path.exists()
        and not _is_reparse(candidate.path)
    )


def _remove_path(path: Path) -> None:
    if _is_reparse(path) or path.is_symlink() or path.is_file():
        path.unlink()
        return
    for child in tuple(path.iterdir()):
        _remove_path(child)
    path.rmdir()


def _cleanup_marker_version(marker: Path) -> tuple[int, int, int] | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _version_tuple(str(data.get("target_version", "")))


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    parts = value.strip().removeprefix("v").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _is_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def _file_size(path: Path) -> int:
    try:
        return max(0, path.lstat().st_size)
    except OSError:
        return 0


def _existing_ancestor(path: Path) -> Path:
    current = _safe_resolve(path)
    while not current.exists() and current.parent != current:
        current = current.parent
    return current
