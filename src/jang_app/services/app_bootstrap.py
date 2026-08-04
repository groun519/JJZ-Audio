from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths, STORAGE_LAYOUT_VERSION
from jang_app.services.managed_files import copy_file_atomic, write_json_atomic


_LEGACY_SETTINGS_FILES = ("app_settings.json", "song_library.json", "work_song.json")
_MIGRATION_FILE_NAME = "source-layout-v1.json"


@dataclass(frozen=True)
class AppBootstrapResult:
    copied_settings: tuple[Path, ...]
    storage_file: Path
    migration_file: Path


def prepare_app_environment(paths: AppPaths | None = None) -> AppBootstrapResult:
    if paths is None:
        from jang_app.config import APP_PATHS

        paths = APP_PATHS

    for directory in (
        paths.settings_dir,
        paths.log_dir,
        paths.cache_dir,
        paths.workspace_root,
        paths.output_root / "downloads",
        paths.output_root / "separations",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    copied = _copy_legacy_settings(paths)
    write_json_atomic(
        paths.storage_file,
        {
            "version": STORAGE_LAYOUT_VERSION,
            "workspace_root": str(paths.workspace_root),
            "workspace_anchor": str(paths.workspace_anchor),
        },
    )

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
                "copied_settings": [path.name for path in copied],
            },
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
