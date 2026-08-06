from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from jang_app.services.app_paths import AppPaths
from jang_app.services.initial_setup import (
    InitialSetupError,
    build_storage_layout,
    persist_storage_layout,
    prepare_storage_layout,
)
from jang_app.services.managed_files import copy_file_atomic, file_sha256, write_json_atomic


StorageProgress = Callable[[str, int], None]


class StorageMigrationError(RuntimeError):
    """Raised when a storage relocation cannot complete without risking user data."""


@dataclass(frozen=True)
class StorageMigrationComponent:
    name: str
    source: Path
    target: Path
    file_count: int
    size_bytes: int


@dataclass(frozen=True)
class StorageMigrationPlan:
    current: AppPaths
    configured: AppPaths
    components: tuple[StorageMigrationComponent, ...]
    total_files: int
    total_bytes: int

    @property
    def required(self) -> bool:
        return bool(self.components)

    @property
    def required_free_bytes(self) -> int:
        headroom = min(
            2 * 1024**3,
            max(512 * 1024**2, self.total_bytes // 10),
        )
        return self.total_bytes + headroom if self.required else 0


def plan_storage_migration(paths: AppPaths, storage_root: Path) -> StorageMigrationPlan:
    try:
        configured = build_storage_layout(paths, storage_root)
    except InitialSetupError as exc:
        raise StorageMigrationError(str(exc)) from exc

    pairs = (
        ("Data", paths.workspace_root, configured.workspace_root),
        ("Output", paths.output_root, configured.output_root),
        ("Runtime", paths.runtime_root, configured.runtime_root),
        ("Cache", paths.cache_dir, configured.cache_dir),
    )
    components: list[StorageMigrationComponent] = []
    for name, source, target in pairs:
        source = source.expanduser().resolve()
        target = target.expanduser().resolve()
        if source == target or not source.exists():
            continue
        if _is_within(configured.storage_root, source):
            raise StorageMigrationError(
                f"Storage location cannot be placed inside the current {name} folder."
            )
        if _contains_files(target):
            raise StorageMigrationError(
                f"The target {name} folder already contains files: {target}"
            )
        files = tuple(_component_files(source))
        if not files:
            continue
        components.append(
            StorageMigrationComponent(
                name=name,
                source=source,
                target=target,
                file_count=len(files),
                size_bytes=sum(path.stat().st_size for path in files),
            )
        )
    plan = StorageMigrationPlan(
        current=paths,
        configured=configured,
        components=tuple(components),
        total_files=sum(component.file_count for component in components),
        total_bytes=sum(component.size_bytes for component in components),
    )
    if plan.required:
        disk_root = _nearest_existing_parent(configured.storage_root)
        free_bytes = shutil.disk_usage(disk_root).free
        if free_bytes < plan.required_free_bytes:
            raise StorageMigrationError(
                "The selected storage does not have enough free space. "
                f"Required: {_format_bytes(plan.required_free_bytes)}, "
                f"available: {_format_bytes(free_bytes)}."
            )
    return plan


def migrate_storage(
    plan: StorageMigrationPlan,
    progress: StorageProgress | None = None,
) -> AppPaths:
    if not plan.required:
        configured = prepare_storage_layout(plan.current, plan.configured.storage_root)
        persist_storage_layout(configured)
        _report(progress, "Storage ready", 100)
        return configured

    root = plan.configured.storage_root
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".jjzero-migration-{uuid4().hex}"
    staging.mkdir()
    copied_bytes = 0

    def copy_progress(base: int, value: int) -> None:
        completed = base + value
        percent = int(completed * 80 / max(1, plan.total_bytes))
        _report(progress, "Copying files", min(80, percent))

    try:
        for component in plan.components:
            stage_target = staging / component.name
            stage_target.mkdir(parents=True)
            component_base = copied_bytes
            for source in _component_files(component.source):
                relative = source.relative_to(component.source)
                file_base = copied_bytes
                copy_file_atomic(
                    source,
                    stage_target / relative,
                    lambda value, base=file_base: copy_progress(base, value),
                )
                copied_bytes += source.stat().st_size
            if component.size_bytes == 0:
                _report(progress, f"Preparing {component.name}", 80)
            elif copied_bytes < component_base + component.size_bytes:
                raise StorageMigrationError(f"{component.name} copy did not complete.")

        _report(progress, "Verifying copied files", 82)
        _verify_staging(plan, staging, progress)
        _rebase_json_paths(plan, staging)
        _report(progress, "Activating storage", 94)
        for component in plan.components:
            staged = staging / component.name
            target = component.target
            if target.exists():
                _remove_empty_tree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)

        _rebase_settings_paths(plan)
        configured = prepare_storage_layout(plan.current, root)
        persist_storage_layout(configured)
        _report(progress, "Storage ready", 100)
        return configured
    except (OSError, ValueError) as exc:
        raise StorageMigrationError(f"Storage migration failed: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _verify_staging(
    plan: StorageMigrationPlan,
    staging: Path,
    progress: StorageProgress | None,
) -> None:
    verified = 0
    total = max(1, plan.total_files)
    for component in plan.components:
        stage_root = staging / component.name
        for source in _component_files(component.source):
            target = stage_root / source.relative_to(component.source)
            if not target.is_file() or source.stat().st_size != target.stat().st_size:
                raise StorageMigrationError(f"Copied file is incomplete: {source.name}")
            if file_sha256(source) != file_sha256(target):
                raise StorageMigrationError(f"Copied file verification failed: {source.name}")
            verified += 1
            _report(progress, "Verifying copied files", 82 + int(10 * verified / total))


def _rebase_json_paths(plan: StorageMigrationPlan, staging: Path) -> None:
    replacements = tuple(
        (component.source, component.target)
        for component in plan.components
    )
    for path in staging.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rebased = _rebase_json_value(
            data,
            replacements,
            project_roots=(plan.current.workspace_anchor, plan.configured.workspace_anchor),
        )
        if rebased != data and isinstance(rebased, dict):
            write_json_atomic(path, rebased)


def _rebase_settings_paths(plan: StorageMigrationPlan) -> None:
    replacements = tuple(
        (component.source, component.target)
        for component in plan.components
    )
    for name in ("app_settings.json", "song_library.json", "work_song.json"):
        path = plan.current.settings_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rebased = _rebase_json_value(
            data,
            replacements,
            project_roots=(plan.current.workspace_anchor, plan.configured.workspace_anchor),
        )
        if rebased != data and isinstance(rebased, dict):
            write_json_atomic(path, rebased)


def _rebase_json_value(
    value: object,
    replacements: tuple[tuple[Path, Path], ...],
    *,
    project_roots: tuple[Path, Path],
) -> object:
    if isinstance(value, dict):
        return {
            key: _rebase_json_value(
                item,
                replacements,
                project_roots=project_roots,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rebase_json_value(
                item,
                replacements,
                project_roots=project_roots,
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value
    if value.startswith("@project/"):
        return _rebase_project_path(value, replacements, project_roots)
    if value.startswith("@"):
        return value
    for source, target in replacements:
        rebased = _replace_path_prefix(value, source, target)
        if rebased is not None:
            return rebased
    return value


def _rebase_project_path(
    value: str,
    replacements: tuple[tuple[Path, Path], ...],
    project_roots: tuple[Path, Path],
) -> str:
    source_root, target_root = (path.resolve() for path in project_roots)
    relative = Path(value.removeprefix("@project/"))
    if relative.is_absolute() or ".." in relative.parts:
        return value
    source_path = (source_root / relative).resolve()
    for source, target in replacements:
        rebased = _replace_path_prefix(str(source_path), source, target)
        if rebased is None:
            continue
        target_path = Path(rebased).resolve()
        try:
            target_relative = target_path.relative_to(target_root)
        except ValueError:
            return str(target_path)
        return f"@project/{target_relative.as_posix()}"
    return str(source_path)


def _replace_path_prefix(value: str, source: Path, target: Path) -> str | None:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        relative = candidate.resolve().relative_to(source)
    except ValueError:
        return None
    return str(target / relative)


def _component_files(root: Path):
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    yield from (path for path in root.rglob("*") if path.is_file())


def _contains_files(path: Path) -> bool:
    return path.is_file() or (path.is_dir() and any(item.is_file() for item in path.rglob("*")))


def _remove_empty_tree(path: Path) -> None:
    if path.is_file():
        raise StorageMigrationError(f"Storage target is a file: {path}")
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_file():
            raise StorageMigrationError(f"Storage target is not empty: {path}")
        child.rmdir()
    path.rmdir()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{amount:.0f} {unit}"
        amount /= 1024
    return f"{value} B"


def _report(progress: StorageProgress | None, stage: str, percent: int) -> None:
    if progress is not None:
        progress(stage, max(0, min(100, percent)))
