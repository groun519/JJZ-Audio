from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_bootstrap import prepare_app_environment
from jang_app.services.app_paths import discover_app_paths
from jang_app.services.update_cache import mark_update_cleanup_ready
from jang_app.version import __version__


class AppBootstrapTests(unittest.TestCase):
    def test_bootstrap_cleans_completed_updates_and_preserves_partial_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(root / "data")},
                frozen=False,
                source_root=source,
            )
            completed = paths.cache_dir / "updates" / "0.3.0"
            installer = completed / "setup.exe"
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b"installer")
            self.assertTrue(
                mark_update_cleanup_ready(paths.cache_dir, completed, "0.3.0")
            )
            partial = paths.cache_dir / "updates" / __version__ / "setup.exe.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")

            prepare_app_environment(paths)

            self.assertFalse(completed.exists())
            self.assertTrue(partial.is_file())

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

    def test_frozen_legacy_install_settings_are_copied_without_moving_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            install = root / "install"
            data_root = root / "data"
            package.mkdir(parents=True)
            song = install / "workspace" / "library" / "songs" / "song-a" / "song.json"
            song.parent.mkdir(parents=True)
            song.write_text("{}", encoding="utf-8")
            legacy_settings = install / "settings"
            legacy_settings.mkdir()
            (legacy_settings / "app_settings.json").write_text("legacy-settings", encoding="utf-8")

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=install / "JJZero Audio.exe",
                source_root=source,
            )
            result = prepare_app_environment(paths)

            copied = data_root / "settings" / "app_settings.json"
            self.assertEqual(copied.read_text(encoding="utf-8"), "legacy-settings")
            self.assertEqual(paths.workspace_root, (install / "workspace").resolve())
            self.assertEqual(result.copied_settings, (copied,))

    def test_repairs_missing_rvc_device_adapter_during_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(root / "data")},
                frozen=False,
                source_root=source,
            )
            rvc_root = paths.runtime_root / "rvc"
            rvc_root.mkdir(parents=True)

            prepare_app_environment(paths)

            adapter = rvc_root / "lib" / "jjzero_device.py"
            self.assertTrue(adapter.is_file())
            self.assertIn("resolve_torch_device", adapter.read_text(encoding="utf-8"))

    def test_bootstrap_promotes_v2_paths_to_v3_without_moving_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            data_root = root / "local"
            storage_root = root / "storage"
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            storage_file = settings / "storage.json"
            storage_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "storage_root": str(storage_root),
                        "workspace_root": str(storage_root / "Data"),
                        "workspace_anchor": str(storage_root),
                        "output_root": str(storage_root / "Output"),
                        "runtime_root": str(storage_root / "Runtime"),
                        "cache_root": str(storage_root / "Cache"),
                    }
                ),
                encoding="utf-8",
            )
            song = storage_root / "Data" / "song.wav"
            song.parent.mkdir(parents=True)
            song.write_bytes(b"audio")
            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            prepare_app_environment(paths)
            promoted = json.loads(storage_file.read_text(encoding="utf-8"))

            self.assertEqual(promoted["version"], 3)
            self.assertEqual(promoted["mode"], "linked")
            self.assertTrue(song.is_file())

    def test_bootstrap_promotes_v1_directly_to_v3_without_moving_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            data_root = root / "local"
            workspace = root / "legacy" / "workspace"
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            storage_file = settings / "storage.json"
            storage_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "workspace_root": str(workspace),
                        "workspace_anchor": str(workspace.parent),
                    }
                ),
                encoding="utf-8",
            )
            song = workspace / "song.wav"
            song.parent.mkdir(parents=True)
            song.write_bytes(b"audio")
            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            prepare_app_environment(paths)
            promoted = json.loads(storage_file.read_text(encoding="utf-8"))

            self.assertEqual(promoted["version"], 3)
            self.assertEqual(Path(promoted["workspace_root"]), workspace.resolve())
            self.assertEqual(promoted["mode"], "custom")
            self.assertTrue(song.is_file())


if __name__ == "__main__":
    unittest.main()
