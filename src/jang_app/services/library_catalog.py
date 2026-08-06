from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from jang_app.services.app_paths import AppPaths
    from jang_app.services.rvc_model_workspace import RvcModelRecord
    from jang_app.services.song_package import SongPackage


CATALOG_SCHEMA_VERSION = 1


class LibraryCatalog:
    """Rebuildable SQLite index for song and model package manifests."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            while version < CATALOG_SCHEMA_VERSION:
                migration = _MIGRATIONS.get(version)
                if migration is None:
                    raise RuntimeError(f"Unsupported catalog schema version: {version}")
                migration(connection)
                version += 1
                connection.execute(f"PRAGMA user_version = {version}")
            if version > CATALOG_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Catalog schema {version} is newer than supported schema "
                    f"{CATALOG_SCHEMA_VERSION}."
                )

    def rebuild(
        self,
        songs: Iterable[SongPackage],
        models: Iterable[RvcModelRecord],
    ) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute("DELETE FROM songs")
            connection.execute("DELETE FROM models")
            connection.executemany(_SONG_UPSERT, (_song_values(song) for song in songs))
            connection.executemany(_MODEL_UPSERT, (_model_values(model) for model in models))

    def replace_songs(self, songs: Iterable[SongPackage]) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute("DELETE FROM songs")
            connection.executemany(_SONG_UPSERT, (_song_values(song) for song in songs))

    def upsert_song(self, song: SongPackage) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute(_SONG_UPSERT, _song_values(song))

    def replace_models(self, models: Iterable[RvcModelRecord]) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute("DELETE FROM models")
            connection.executemany(_MODEL_UPSERT, (_model_values(model) for model in models))

    def counts(self) -> tuple[int, int]:
        self.ensure_schema()
        with self._connect() as connection:
            songs = int(connection.execute("SELECT COUNT(*) FROM songs").fetchone()[0])
            models = int(connection.execute("SELECT COUNT(*) FROM models").fetchone()[0])
        return songs, models

    def metadata(self, key: str) -> str:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row[0]) if row is not None else ""

    def set_metadata(self, key: str, value: str) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                yield connection
        finally:
            connection.close()


def rebuild_library_catalog(paths: AppPaths) -> LibraryCatalog:
    from jang_app.services.rvc_model_workspace import RvcModelWorkspace
    from jang_app.services.song_package import SongPackageStore

    song_store = SongPackageStore(
        paths.workspace_root / "library" / "songs",
        paths.workspace_anchor,
        catalog_file=paths.catalog_file,
    )
    model_store = RvcModelWorkspace(
        paths.workspace_root / "models",
        catalog_file=paths.catalog_file,
    )
    songs = song_store.packages(include_removed=True)
    models = model_store.records()
    catalog = LibraryCatalog(paths.catalog_file)
    catalog.rebuild(songs, models)
    catalog.set_metadata("source_signature", catalog_source_signature(paths))
    return catalog


def synchronize_library_catalog(paths: AppPaths) -> LibraryCatalog:
    catalog = LibraryCatalog(paths.catalog_file)
    signature = catalog_source_signature(paths)
    try:
        is_current = (
            catalog.path.is_file()
            and catalog.metadata("source_signature") == signature
        )
    except sqlite3.DatabaseError:
        _quarantine_corrupt_catalog(catalog.path)
        is_current = False
    if not is_current:
        return rebuild_library_catalog(paths)
    return catalog


def catalog_source_signature(paths: AppPaths) -> str:
    candidates = [
        *(paths.workspace_root / "library" / "songs").glob("*/song.json"),
        paths.workspace_root / "models" / "catalog.json",
        *(paths.workspace_root / "models" / "library").glob("*/model.json"),
    ]
    digest = sha256()
    for path in sorted(
        (candidate.resolve() for candidate in candidates if candidate.is_file()),
        key=lambda item: str(item).casefold(),
    ):
        stat = path.stat()
        digest.update(str(path).casefold().encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def inferred_catalog_file(store_root: Path, kind: str) -> Path:
    root = store_root.expanduser().resolve()
    if kind == "songs":
        return root.parent.parent / "catalog.db"
    if kind == "models":
        return root.parent / "catalog.db"
    raise ValueError(f"Unsupported catalog store kind: {kind}")


def _quarantine_corrupt_catalog(path: Path) -> None:
    if not path.exists():
        return
    quarantine = path.with_suffix(f"{path.suffix}.corrupt")
    if quarantine.exists():
        quarantine.unlink()
    path.replace(quarantine)


def _migrate_v0_to_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE songs (
            song_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            package_dir TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            removed INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX songs_title_idx ON songs(normalized_title);
        CREATE INDEX songs_source_type_idx ON songs(source_type);

        CREATE TABLE models (
            model_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            mode TEXT NOT NULL,
            package_dir TEXT NOT NULL,
            inference_model TEXT NOT NULL,
            index_file TEXT NOT NULL,
            status_key TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX models_title_idx ON models(normalized_title);
        CREATE INDEX models_status_idx ON models(status_key);

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


_MIGRATIONS = {
    0: _migrate_v0_to_v1,
}

_SONG_UPSERT = """
    INSERT INTO songs (
        song_id, title, normalized_title, package_dir, source_path,
        source_type, source_url, created_at, removed
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(song_id) DO UPDATE SET
        title = excluded.title,
        normalized_title = excluded.normalized_title,
        package_dir = excluded.package_dir,
        source_path = excluded.source_path,
        source_type = excluded.source_type,
        source_url = excluded.source_url,
        created_at = excluded.created_at,
        removed = excluded.removed
"""

_MODEL_UPSERT = """
    INSERT INTO models (
        model_id, title, normalized_title, mode, package_dir,
        inference_model, index_file, status_key, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(model_id) DO UPDATE SET
        title = excluded.title,
        normalized_title = excluded.normalized_title,
        mode = excluded.mode,
        package_dir = excluded.package_dir,
        inference_model = excluded.inference_model,
        index_file = excluded.index_file,
        status_key = excluded.status_key,
        created_at = excluded.created_at
"""


def _song_values(song: SongPackage) -> tuple[object, ...]:
    return (
        song.song_id,
        song.title,
        song.title.casefold(),
        str(song.folder),
        str(song.source_path or ""),
        song.source_type,
        song.source_url,
        song.created_at,
        int(song.removed),
    )


def _model_values(model: RvcModelRecord) -> tuple[object, ...]:
    return (
        model.model_id,
        model.title,
        model.title.casefold(),
        model.mode,
        str(model.primary_location),
        str(model.inference_model or ""),
        str(model.index_file or ""),
        model.status_key,
        model.created_at,
    )
