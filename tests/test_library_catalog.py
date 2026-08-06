from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jang_app.services.library_catalog import LibraryCatalog, synchronize_library_catalog
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.song_package import SongPackageStore


class LibraryCatalogTests(unittest.TestCase):
    def test_song_and_model_manifests_update_shared_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "Data"
            catalog_path = workspace / "catalog.db"
            audio = root / "voice.wav"
            audio.write_bytes(b"audio")
            model_file = root / "voice.pth"
            model_file.write_bytes(b"model")

            song_store = SongPackageStore(
                workspace / "library" / "songs",
                root,
                catalog_file=catalog_path,
            )
            model_store = RvcModelWorkspace(
                workspace / "models",
                catalog_file=catalog_path,
            )
            song_store.import_audio(audio, title="Catalog Song")
            model_store.link_inference_file(model_file)

            catalog = LibraryCatalog(catalog_path)
            self.assertEqual(catalog.counts(), (1, 1))
            connection = sqlite3.connect(catalog_path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT title FROM songs").fetchone()[0],
                    "Catalog Song",
                )
                self.assertEqual(
                    connection.execute("SELECT title FROM models").fetchone()[0],
                    "voice",
                )
            finally:
                connection.close()

    def test_catalog_can_be_rebuilt_from_canonical_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "Data"
            audio = root / "source.wav"
            audio.write_bytes(b"audio")
            song_store = SongPackageStore(workspace / "library" / "songs", root)
            song_store.import_audio(audio, title="Rebuild Source")
            songs = song_store.packages(include_removed=True)

            catalog = LibraryCatalog(workspace / "catalog.db")
            catalog.rebuild(songs, ())
            self.assertEqual(catalog.counts(), (1, 0))

    def test_corrupt_catalog_is_quarantined_and_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "Data"
            workspace.mkdir(parents=True)
            catalog_path = workspace / "catalog.db"
            catalog_path.write_bytes(b"not a sqlite database")
            paths = _paths(root, workspace)

            catalog = synchronize_library_catalog(paths)

            self.assertEqual(catalog.counts(), (0, 0))
            self.assertTrue(workspace.joinpath("catalog.db.corrupt").is_file())


def _paths(root: Path, workspace: Path):
    from jang_app.services.app_paths import discover_app_paths

    source = root / "source"
    package = source / "src" / "jang_app"
    package.mkdir(parents=True)
    settings = root / "local" / "settings"
    settings.mkdir(parents=True)
    settings.joinpath("storage.json").write_text(
        json.dumps(
            {
                "version": 2,
                "storage_root": str(root),
                "workspace_root": str(workspace),
                "workspace_anchor": str(root),
                "output_root": str(root / "Output"),
                "runtime_root": str(root / "Runtime"),
                "cache_root": str(root / "Cache"),
            }
        ),
        encoding="utf-8",
    )
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "local")},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=source,
    )


if __name__ == "__main__":
    unittest.main()
