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
    prepare_configured_storage_layout,
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
    transaction_id: str
    cache_reset: bool = False

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


def plan_storage_migration(
    paths: AppPaths,
    storage: Path | AppPaths,
) -> StorageMigrationPlan:
    try:
        configured = storage if isinstance(storage, AppPaths) else build_storage_layout(paths, storage)
    except InitialSetupError as exc:
        raise StorageMigrationError(str(exc)) from exc

    pairs = (
        ("Data", paths.workspace_root, configured.workspace_root),
        ("Output", paths.output_root, configured.output_root),
        ("Runtime", paths.runtime_root, configured.runtime_root),
    )
    components: list[StorageMigrationComponent] = []
    for name, source, target in pairs:
        source = source.expanduser().resolve()
        target = target.expanduser().resolve()
        if source == target or not source.exists():
            continue
        if _is_within(target, source):
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
        transaction_id=uuid4().hex,
        cache_reset=paths.cache_dir.resolve() != configured.cache_dir.resolve(),
    )
    for disk_root, components_on_disk in _components_by_disk(plan.components):
        required_bytes = sum(component.size_bytes for component in components_on_disk)
        required_free = _required_free_bytes(required_bytes)
        free_bytes = shutil.disk_usage(disk_root).free
        if free_bytes < required_free:
            raise StorageMigrationError(
                "The selected storage does not have enough free space. "
                f"Required: {_format_bytes(required_free)}, "
                f"available: {_format_bytes(free_bytes)}."
            )
    return plan


def migrate_storage(
    plan: StorageMigrationPlan,
    progress: StorageProgress | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> AppPaths:
    if not plan.required:
        configured = prepare_configured_storage_layout(plan.configured)
        persist_storage_layout(configured)
        _report(progress, "Storage ready", 100)
        return configured

    staging = {
        component.name: component.target.parent
        / f".jjzero-migration-{plan.transaction_id}-{component.name.lower()}"
        for component in plan.components
    }
    for path in staging.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
    journal = _write_migration_journal(plan, "copying", staging)
    copied_bytes = 0

    def copy_progress(component_name: str, base: int, value: int) -> None:
        completed = base + value
        percent = int(completed * 80 / max(1, plan.total_bytes))
        _report(progress, f"Copying {component_name}", min(80, percent))

    try:
        for component in plan.components:
            _raise_if_cancelled(cancelled)
            stage_target = staging[component.name]
            component_base = copied_bytes
            for source in _component_files(component.source):
                _raise_if_cancelled(cancelled)
                relative = source.relative_to(component.source)
                file_base = copied_bytes

                def report_file_progress(
                    value: int,
                    *,
                    base: int = file_base,
                    component_name: str = component.name,
                ) -> None:
                    _raise_if_cancelled(cancelled)
                    copy_progress(component_name, base, value)

                copy_file_atomic(
                    source,
                    stage_target / relative,
                    report_file_progress,
                )
                copied_bytes += source.stat().st_size
            if component.size_bytes == 0:
                _report(progress, f"Preparing {component.name}", 80)
            elif copied_bytes < component_base + component.size_bytes:
                raise StorageMigrationError(f"{component.name} copy did not complete.")

        _report(progress, "Verifying copied files", 82)
        _update_migration_journal(journal, "verifying")
        _verify_staging(plan, staging, progress)
        _rebase_json_paths(plan, staging)
        _raise_if_cancelled(cancelled)
        _report(progress, "Activating storage", 94)
        _update_migration_journal(journal, "activating")
        for component in plan.components:
            staged = staging[component.name]
            target = component.target
            if target.exists():
                _remove_empty_tree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            _record_activated_component(journal, component.name)

        _rebase_settings_paths(plan)
        configured = prepare_configured_storage_layout(plan.configured)
        persist_storage_layout(configured)
        _update_migration_journal(journal, "ready")
        _report(progress, "Storage ready", 100)
        return configured
    except StorageMigrationError:
        _update_migration_journal(journal, "cancelled" if cancelled and cancelled() else "failed")
        raise
    except (OSError, ValueError) as exc:
        _update_migration_journal(journal, "failed", error=str(exc))
        raise StorageMigrationError(f"Storage migration failed: {exc}") from exc
    finally:
        for path in staging.values():
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)


def recover_storage_migrations(paths: AppPaths) -> tuple[Path, ...]:
    migration_dir = paths.data_root / "migrations"
    if not migration_dir.is_dir():
        return ()
    recovered: list[Path] = []
    active_roots = {
        path.resolve()
        for path in (
            paths.workspace_root,
            paths.output_root,
            paths.runtime_root,
            paths.cache_dir,
        )
    }
    for journal in migration_dir.glob("storage-relocation-*.json"):
        try:
            data = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("status") == "ready":
            continue
        for value in data.get("staging", {}).values() if isinstance(data.get("staging"), dict) else ():
            path = Path(str(value)).expanduser()
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        activated = set(data.get("activated", ()))
        targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
        for name in activated:
            value = targets.get(name)
            if not value:
                continue
            target = Path(str(value)).expanduser().resolve()
            if target in active_roots:
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
        _update_migration_journal(journal, "recovered")
        recovered.append(journal)
    return tuple(recovered)


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise StorageMigrationError("Storage migration was cancelled. Original data was not changed.")


def _write_migration_journal(
    plan: StorageMigrationPlan,
    status: str,
    staging: dict[str, Path],
) -> Path:
    journal = (
        plan.current.data_root
        / "migrations"
        / f"storage-relocation-{plan.transaction_id}.json"
    )
    write_json_atomic(
        journal,
        {
            "version": 1,
            "transaction_id": plan.transaction_id,
            "status": status,
            "staging": {name: str(path) for name, path in staging.items()},
            "targets": {component.name: str(component.target) for component in plan.components},
            "activated": [],
        },
    )
    return journal


def _update_migration_journal(journal: Path, status: str, *, error: str = "") -> None:
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"version": 1}
    if not isinstance(data, dict):
        data = {"version": 1}
    data["status"] = status
    if error:
        data["error"] = error
    write_json_atomic(journal, data)


def _record_activated_component(journal: Path, name: str) -> None:
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageMigrationError(f"Could not update storage migration journal: {exc}") from exc
    activated = list(data.get("activated", ()))
    if name not in activated:
        activated.append(name)
    data["activated"] = activated
    write_json_atomic(journal, data)


def _verify_staging(
    plan: StorageMigrationPlan,
    staging: dict[str, Path],
    progress: StorageProgress | None,
) -> None:
    verified = 0
    total = max(1, plan.total_files)
    for component in plan.components:
        stage_root = staging[component.name]
        for source in _component_files(component.source):
            target = stage_root / source.relative_to(component.source)
            if not target.is_file() or source.stat().st_size != target.stat().st_size:
                raise StorageMigrationError(f"Copied file is incomplete: {source.name}")
            if file_sha256(source) != file_sha256(target):
                raise StorageMigrationError(f"Copied file verification failed: {source.name}")
            verified += 1
            _report(
                progress,
                f"Verifying {component.name}",
                82 + int(10 * verified / total),
            )


def _rebase_json_paths(plan: StorageMigrationPlan, staging: dict[str, Path]) -> None:
    replacements = tuple(
        (component.source, component.target)
        for component in plan.components
    )
    for path in (
        path
        for stage_root in staging.values()
        for path in stage_root.rglob("*.json")
    ):
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


def _components_by_disk(
    components: tuple[StorageMigrationComponent, ...],
) -> tuple[tuple[Path, tuple[StorageMigrationComponent, ...]], ...]:
    grouped: dict[Path, list[StorageMigrationComponent]] = {}
    for component in components:
        disk = _nearest_existing_parent(component.target)
        anchor = Path(disk.anchor) if disk.anchor else disk
        grouped.setdefault(anchor, []).append(component)
    return tuple((root, tuple(items)) for root, items in grouped.items())


def _required_free_bytes(total_bytes: int) -> int:
    if total_bytes <= 0:
        return 0
    headroom = min(2 * 1024**3, max(512 * 1024**2, total_bytes // 10))
    return total_bytes + headroom


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
