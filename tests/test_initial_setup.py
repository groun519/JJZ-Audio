from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.initial_setup import (
    InitialSetupError,
    complete_initial_setup,
    is_initial_setup_complete,
    prepare_storage_layout,
)


class InitialSetupTests(unittest.TestCase):
    def test_prepares_and_persists_selected_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            media = root / "media"

            configured = prepare_storage_layout(paths, media)
            marker = complete_initial_setup(configured, diagnostics_ready=True)
            storage = json.loads(configured.storage_file.read_text(encoding="utf-8"))

            self.assertEqual(configured.storage_root, media)
            self.assertEqual(configured.workspace_root, media / "Data")
            self.assertEqual(configured.output_root, media / "Output")
            self.assertEqual(configured.runtime_root, media / "Runtime")
            self.assertEqual(configured.cache_dir, media / "Cache")
            self.assertEqual(Path(storage["workspace_root"]), media / "Data")
            self.assertEqual(Path(storage["storage_root"]), media)
            self.assertTrue(marker.is_file())
            self.assertTrue(is_initial_setup_complete(configured))

    def test_rejects_storage_inside_application_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)

            with self.assertRaises(InitialSetupError):
                prepare_storage_layout(paths, paths.install_root / "user-data")


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "data"), "USERPROFILE": str(root / "user")},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=root / "source",
    )


if __name__ == "__main__":
    unittest.main()
