from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_paths import APP_DATA_DIR_NAME, discover_app_paths


class AppPathsTests(unittest.TestCase):
    def test_fresh_install_separates_install_data_and_workspace_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            local_data = root / "local"
            user_home = root / "user"

            paths = discover_app_paths(
                package,
                environ={"LOCALAPPDATA": str(local_data), "USERPROFILE": str(user_home)},
                frozen=True,
                executable=root / "install" / "JJZeroAudio.exe",
                source_root=source,
            )

            self.assertEqual(paths.install_root, (root / "install").resolve())
            self.assertEqual(paths.data_root, (local_data / APP_DATA_DIR_NAME).resolve())
            self.assertEqual(
                paths.workspace_root,
                (user_home / "Music" / APP_DATA_DIR_NAME / "workspace").resolve(),
            )
            self.assertEqual(paths.runtime_root, (root / "install" / "runtime").resolve())

    def test_development_layout_reuses_existing_workspace_without_moving_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "project"
            package = source / "src" / "jang_app"
            (source / "workspace" / "library").mkdir(parents=True)
            package.mkdir(parents=True)

            paths = discover_app_paths(
                package,
                environ={"LOCALAPPDATA": str(source / "local")},
                frozen=False,
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (source / "workspace").resolve())
            self.assertEqual(paths.workspace_anchor, source.resolve())
            self.assertEqual(paths.output_root, (source / "output").resolve())
            self.assertEqual(paths.runtime_root, (source / "third_party").resolve())

    def test_persisted_storage_layout_takes_priority_over_legacy_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "data"
            workspace = root / "external" / "workspace"
            anchor = workspace.parent
            (source / "workspace" / "legacy").mkdir(parents=True)
            package.mkdir(parents=True)
            storage = data_root / "settings" / "storage.json"
            storage.parent.mkdir(parents=True)
            storage.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "workspace_root": str(workspace),
                        "workspace_anchor": str(anchor),
                    }
                ),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=False,
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, workspace.resolve())
            self.assertEqual(paths.workspace_anchor, anchor.resolve())


if __name__ == "__main__":
    unittest.main()
