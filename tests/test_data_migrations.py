from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.data_migrations import run_data_migrations
from jang_app.services.song_package import SongPackageStore


class DataMigrationTests(unittest.TestCase):
    def test_missing_migration_state_runs_all_required_schema_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            audio = root / "source.wav"
            audio.write_bytes(b"audio")
            SongPackageStore(
                paths.workspace_root / "library" / "songs",
                paths.workspace_anchor,
                catalog_file=paths.catalog_file,
            ).import_audio(audio, title="Migrated Song")

            result = run_data_migrations(paths)
            state_path = paths.data_root / "migrations" / "data-schema.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual(result.previous_schema, 0)
            self.assertEqual(result.current_schema, 1)
            self.assertEqual(result.applied, ("library-catalog-v1",))
            self.assertEqual(result.catalog.counts(), (1, 0))
            self.assertEqual(state["schema"], 1)

    def test_current_schema_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))

            run_data_migrations(paths)
            result = run_data_migrations(paths)

            self.assertEqual(result.previous_schema, 1)
            self.assertEqual(result.applied, ())

    def test_current_schema_does_not_rewrite_unchanged_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            run_data_migrations(paths)

            with patch(
                "jang_app.services.data_migrations.write_json_atomic"
            ) as write_state:
                result = run_data_migrations(paths)

            self.assertEqual(result.applied, ())
            write_state.assert_not_called()

    def test_newer_data_schema_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            state_path = paths.data_root / "migrations" / "data-schema.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps({"version": 1, "schema": 99, "applied": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                run_data_migrations(paths)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["schema"],
                99,
            )


def _paths(root: Path):
    source = root / "source"
    package = source / "src" / "jang_app"
    package.mkdir(parents=True)
    storage = root / "storage"
    settings = root / "local" / "settings"
    settings.mkdir(parents=True)
    (settings / "storage.json").write_text(
        json.dumps(
            {
                "version": 2,
                "storage_root": str(storage),
                "workspace_root": str(storage / "Data"),
                "workspace_anchor": str(storage),
                "output_root": str(storage / "Output"),
                "runtime_root": str(storage / "Runtime"),
                "cache_root": str(storage / "Cache"),
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
