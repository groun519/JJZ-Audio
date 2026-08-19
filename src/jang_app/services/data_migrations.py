from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.library_catalog import LibraryCatalog, synchronize_library_catalog
from jang_app.services.managed_files import write_json_atomic


DATA_SCHEMA_VERSION = 1
MIGRATION_STATE_VERSION = 1
MIGRATION_STATE_FILE_NAME = "data-schema.json"


@dataclass(frozen=True)
class DataMigrationResult:
    previous_schema: int
    current_schema: int
    applied: tuple[str, ...]
    catalog: LibraryCatalog


@dataclass(frozen=True)
class _Migration:
    schema: int
    migration_id: str
    apply: Callable[[AppPaths], None]


@dataclass(frozen=True)
class _MigrationState:
    schema: int
    applied: tuple[str, ...]


def run_data_migrations(paths: AppPaths) -> DataMigrationResult:
    state_path = paths.data_root / "migrations" / MIGRATION_STATE_FILE_NAME
    state = _load_state(state_path)
    previous_schema = state.schema
    if previous_schema > DATA_SCHEMA_VERSION:
        raise RuntimeError(
            f"Data schema {previous_schema} is newer than supported schema "
            f"{DATA_SCHEMA_VERSION}."
        )
    applied_ids = set(state.applied)
    newly_applied: list[str] = []

    for migration in _MIGRATIONS:
        if migration.schema <= previous_schema and migration.migration_id in applied_ids:
            continue
        migration.apply(paths)
        applied_ids.add(migration.migration_id)
        newly_applied.append(migration.migration_id)

    catalog = synchronize_library_catalog(paths)
    if newly_applied or not state_path.is_file() or previous_schema != DATA_SCHEMA_VERSION:
        write_json_atomic(
            state_path,
            {
                "version": MIGRATION_STATE_VERSION,
                "schema": DATA_SCHEMA_VERSION,
                "applied": sorted(applied_ids),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    return DataMigrationResult(
        previous_schema=previous_schema,
        current_schema=DATA_SCHEMA_VERSION,
        applied=tuple(newly_applied),
        catalog=catalog,
    )


def _initialize_library_catalog(paths: AppPaths) -> None:
    synchronize_library_catalog(paths)


def _load_state(path: Path) -> _MigrationState:
    if not path.is_file():
        return _MigrationState(0, ())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _MigrationState(0, ())
    if not isinstance(data, dict) or data.get("version") != MIGRATION_STATE_VERSION:
        return _MigrationState(0, ())
    schema = data.get("schema", 0)
    applied = data.get("applied", [])
    if not isinstance(schema, int) or not isinstance(applied, list):
        return _MigrationState(0, ())
    return _MigrationState(
        max(0, schema),
        tuple(item for item in applied if isinstance(item, str)),
    )


_MIGRATIONS = (
    _Migration(1, "library-catalog-v1", _initialize_library_catalog),
)
