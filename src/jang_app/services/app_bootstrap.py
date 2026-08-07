from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.data_migrations import run_data_migrations
from jang_app.services.initial_setup import persist_storage_layout, promote_storage_layout
from jang_app.services.managed_files import copy_file_atomic, write_json_atomic
from jang_app.services.rvc_runtime_repair import repair_rvc_runtime_adapter
from jang_app.services.storage_migration import recover_storage_migrations


_LEGACY_SETTINGS_FILES = ("app_settings.json", "song_library.json", "work_song.json")
_MIGRATION_FILE_NAME = "source-layout-v1.json"
_LOGGER = logging.getLogger("jang_app")


@dataclass(frozen=True)
class AppBootstrapResult:
    copied_settings: tuple[Path, ...]
    storage_file: Path
    migration_file: Path


def prepare_app_environment(paths: AppPaths | None = None) -> AppBootstrapResult:
    if paths is None:
        from jang_app.config import APP_PATHS

        paths = APP_PATHS

    recovered = recover_storage_migrations(paths)
    if recovered:
        _LOGGER.warning("Recovered interrupted storage migrations: %s", len(recovered))

    for directory in (
        paths.settings_dir,
        paths.log_dir,
        paths.cache_dir,
        paths.workspace_root,
        paths.output_root / "downloads",
        paths.output_root / "separations",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    repair_rvc_runtime_adapter(paths.runtime_root / "rvc")
    copied = _copy_legacy_settings(paths)
    if paths.storage_file.is_file() and paths.storage_version < 3:
        promote_storage_layout(paths)
    elif not paths.storage_file.is_file():
        if paths.storage_version >= 2:
            persist_storage_layout(paths)
        else:
            write_json_atomic(
                paths.storage_file,
                {
                    "version": paths.storage_version,
                    "workspace_root": str(paths.workspace_root),
                    "workspace_anchor": str(paths.workspace_anchor),
                },
            )
    try:
        migrations = run_data_migrations(paths)
        song_count, model_count = migrations.catalog.counts()
        _LOGGER.info(
            "Data schema ready | schema=%s | applied=%s | catalog=%s | songs=%s | models=%s",
            migrations.current_schema,
            ",".join(migrations.applied) or "none",
            migrations.catalog.path,
            song_count,
            model_count,
        )
    except Exception:
        _LOGGER.exception("Library catalog rebuild deferred")

    migration_dir = paths.data_root / "migrations"
    migration_file = migration_dir / _MIGRATION_FILE_NAME
    if not migration_file.exists():
        write_json_atomic(
            migration_file,
            {
                "version": 1,
                "migrated_at": datetime.now(UTC).isoformat(),
                "legacy_root": str(paths.legacy_root) if paths.legacy_root is not None else "",
                "workspace_root": str(paths.workspace_root),
                "workspace_source": paths.workspace_source,
                "copied_settings": [path.name for path in copied],
            },
        )
    _LOGGER.info(
        "Storage layout | source=%s | data=%s | workspace=%s | output=%s | copied_settings=%s",
        paths.workspace_source,
        paths.data_root,
        paths.workspace_root,
        paths.output_root,
        ",".join(path.name for path in copied) or "none",
    )
    return AppBootstrapResult(tuple(copied), paths.storage_file, migration_file)


def _copy_legacy_settings(paths: AppPaths) -> list[Path]:
    if paths.legacy_root is None:
        return []
    source_dir = paths.legacy_root / "settings"
    copied: list[Path] = []
    for name in _LEGACY_SETTINGS_FILES:
        source = source_dir / name
        target = paths.settings_dir / name
        if not source.is_file() or target.exists():
            continue
        copy_file_atomic(source, target)
        copied.append(target)
    return copied
