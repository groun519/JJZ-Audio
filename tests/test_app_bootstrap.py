from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_bootstrap import prepare_app_environment
from jang_app.services.app_paths import discover_app_paths


class AppBootstrapTests(unittest.TestCase):
    def test_legacy_settings_are_copied_once_and_workspace_is_linked_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "data"
            package.mkdir(parents=True)
            (source / "workspace" / "library").mkdir(parents=True)
            legacy_settings = source / "settings"
            legacy_settings.mkdir()
            for name in ("app_settings.json", "song_library.json", "work_song.json"):
                (legacy_settings / name).write_text(f"legacy-{name}", encoding="utf-8")

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=False,
                source_root=source,
            )
            first = prepare_app_environment(paths)
            target = paths.settings_dir / "app_settings.json"
            target.write_text("user-edited", encoding="utf-8")
            second = prepare_app_environment(paths)
            storage = json.loads(paths.storage_file.read_text(encoding="utf-8"))

            self.assertEqual(len(first.copied_settings), 3)
            self.assertEqual(second.copied_settings, ())
            self.assertEqual(target.read_text(encoding="utf-8"), "user-edited")
            self.assertEqual(Path(storage["workspace_root"]), (source / "workspace").resolve())
            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue(paths.cache_dir.is_dir())
            self.assertTrue(first.migration_file.is_file())


if __name__ == "__main__":
    unittest.main()
