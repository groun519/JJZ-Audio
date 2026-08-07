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
            self.assertEqual(paths.workspace_source, "default")
            self.assertEqual(paths.storage_version, 1)

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
            self.assertEqual(paths.workspace_source, "legacy_source")

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
            self.assertEqual(paths.workspace_source, "storage")
            self.assertEqual(paths.storage_version, 1)

    def test_v2_storage_layout_routes_large_mutable_data_to_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "local"
            storage_root = root / "selected-storage"
            package.mkdir(parents=True)
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            (settings / "storage.json").write_text(
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

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.storage_version, 2)
            self.assertEqual(paths.storage_root, storage_root.resolve())
            self.assertEqual(paths.workspace_root, (storage_root / "Data").resolve())
            self.assertEqual(paths.output_root, (storage_root / "Output").resolve())
            self.assertEqual(paths.runtime_root, (storage_root / "Runtime").resolve())
            self.assertEqual(paths.cache_dir, (storage_root / "Cache").resolve())
            self.assertEqual(paths.catalog_file, (storage_root / "Data" / "catalog.db").resolve())

    def test_v3_custom_layout_resolves_each_location_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "local"
            package.mkdir(parents=True)
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            locations = {
                "workspace_root": root / "library",
                "output_root": root / "exports",
                "runtime_root": root / "engine",
                "cache_root": root / "temporary-cache",
            }
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "mode": "custom",
                        "storage_root": str(root / "anchor"),
                        "workspace_anchor": str(root),
                        **{key: str(value) for key, value in locations.items()},
                    }
                ),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.storage_version, 3)
            self.assertEqual(paths.storage_mode, "custom")
            self.assertEqual(paths.workspace_root, locations["workspace_root"].resolve())
            self.assertEqual(paths.output_root, locations["output_root"].resolve())
            self.assertEqual(paths.runtime_root, locations["runtime_root"].resolve())
            self.assertEqual(paths.cache_dir, locations["cache_root"].resolve())

    def test_v3_initial_setup_recovers_all_locations_without_storage_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "local"
            package.mkdir(parents=True)
            locations = {
                "workspace_root": root / "library",
                "output_root": root / "exports",
                "runtime_root": root / "engine",
                "cache_root": root / "temporary-cache",
            }
            setup = data_root / "settings" / "initial_setup.json"
            setup.parent.mkdir(parents=True)
            setup.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "storage_root": str(root / "anchor"),
                        **{key: str(value) for key, value in locations.items()},
                    }
                ),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.storage_version, 2)
            self.assertEqual(paths.workspace_source, "initial_setup")
            self.assertEqual(paths.workspace_root, locations["workspace_root"].resolve())
            self.assertEqual(paths.output_root, locations["output_root"].resolve())
            self.assertEqual(paths.runtime_root, locations["runtime_root"].resolve())
            self.assertEqual(paths.cache_dir, locations["cache_root"].resolve())

    def test_component_environment_overrides_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            storage_root = root / "managed"
            data_root = root / "local"
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "mode": "linked",
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
            overrides = {
                "JJZERO_DATA_ROOT": str(data_root),
                "JJZERO_WORKSPACE_ROOT": str(root / "custom-data"),
                "JJZERO_OUTPUT_ROOT": str(root / "custom-output"),
                "JJZERO_RUNTIME_ROOT": str(root / "custom-runtime"),
                "JJZERO_CACHE_ROOT": str(root / "custom-cache"),
            }

            paths = discover_app_paths(
                package,
                environ=overrides,
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (root / "custom-data").resolve())
            self.assertEqual(paths.output_root, (root / "custom-output").resolve())
            self.assertEqual(paths.runtime_root, (root / "custom-runtime").resolve())
            self.assertEqual(paths.cache_dir, (root / "custom-cache").resolve())
            self.assertEqual(paths.storage_mode, "custom")

    def test_single_component_override_preserves_other_managed_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            storage_root = root / "managed"
            data_root = root / "local"
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "mode": "linked",
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

            paths = discover_app_paths(
                package,
                environ={
                    "JJZERO_DATA_ROOT": str(data_root),
                    "JJZERO_WORKSPACE_ROOT": str(root / "custom-data"),
                },
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (root / "custom-data").resolve())
            self.assertEqual(paths.output_root, (storage_root / "Output").resolve())
            self.assertEqual(paths.runtime_root, (storage_root / "Runtime").resolve())
            self.assertEqual(paths.cache_dir, (storage_root / "Cache").resolve())
            self.assertEqual(paths.storage_mode, "custom")

    def test_storage_root_override_relinks_all_managed_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            package.mkdir(parents=True)
            data_root = root / "local"
            old_root = root / "old"
            new_root = root / "new"
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "mode": "custom",
                        "storage_root": str(old_root),
                        "workspace_root": str(root / "custom-data"),
                        "workspace_anchor": str(root),
                        "output_root": str(root / "custom-output"),
                        "runtime_root": str(root / "custom-runtime"),
                        "cache_root": str(root / "custom-cache"),
                    }
                ),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={
                    "JJZERO_DATA_ROOT": str(data_root),
                    "JJZERO_STORAGE_ROOT": str(new_root),
                },
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (new_root / "Data").resolve())
            self.assertEqual(paths.output_root, (new_root / "Output").resolve())
            self.assertEqual(paths.runtime_root, (new_root / "Runtime").resolve())
            self.assertEqual(paths.cache_dir, (new_root / "Cache").resolve())
            self.assertEqual(paths.storage_mode, "linked")

    def test_frozen_app_recovers_workspace_from_initial_setup_when_storage_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "data"
            media_root = root / "media"
            package.mkdir(parents=True)
            song = media_root / "workspace" / "library" / "songs" / "song-a" / "song.json"
            song.parent.mkdir(parents=True)
            song.write_text("{}", encoding="utf-8")
            setup = data_root / "settings" / "initial_setup.json"
            setup.parent.mkdir(parents=True)
            setup.write_text(
                json.dumps({"version": 1, "media_root": str(media_root)}),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (media_root / "workspace").resolve())
            self.assertEqual(paths.workspace_source, "initial_setup")

    def test_v2_initial_setup_marker_recovers_data_folder_when_storage_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "data"
            storage_root = root / "storage"
            package.mkdir(parents=True)
            song = storage_root / "Data" / "library" / "songs" / "song-a" / "song.json"
            song.parent.mkdir(parents=True)
            song.write_text("{}", encoding="utf-8")
            setup = data_root / "settings" / "initial_setup.json"
            setup.parent.mkdir(parents=True)
            setup.write_text(
                json.dumps({"version": 2, "storage_root": str(storage_root)}),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (storage_root / "Data").resolve())
            self.assertEqual(paths.workspace_source, "initial_setup")
            self.assertEqual(paths.storage_version, 2)
            self.assertEqual(paths.output_root, (storage_root / "Output").resolve())
            self.assertEqual(paths.runtime_root, (storage_root / "Runtime").resolve())

    def test_populated_initial_setup_workspace_recovers_from_empty_stored_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            data_root = root / "data"
            empty_workspace = root / "empty" / "workspace"
            media_root = root / "media"
            package.mkdir(parents=True)
            empty_workspace.mkdir(parents=True)
            song = media_root / "workspace" / "library" / "songs" / "song-a" / "song.json"
            song.parent.mkdir(parents=True)
            song.write_text("{}", encoding="utf-8")
            settings = data_root / "settings"
            settings.mkdir(parents=True)
            (settings / "storage.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "workspace_root": str(empty_workspace),
                        "workspace_anchor": str(empty_workspace.parent),
                    }
                ),
                encoding="utf-8",
            )
            (settings / "initial_setup.json").write_text(
                json.dumps({"version": 1, "media_root": str(media_root)}),
                encoding="utf-8",
            )

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(data_root)},
                frozen=True,
                executable=root / "install" / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (media_root / "workspace").resolve())
            self.assertEqual(paths.workspace_source, "initial_setup")

    def test_frozen_app_recovers_legacy_install_workspace_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            package = source / "src" / "jang_app"
            install = root / "install"
            package.mkdir(parents=True)
            song = install / "workspace" / "library" / "songs" / "song-a" / "song.json"
            song.parent.mkdir(parents=True)
            song.write_text("{}", encoding="utf-8")
            legacy_settings = install / "settings"
            legacy_settings.mkdir()
            (legacy_settings / "app_settings.json").write_text("{}", encoding="utf-8")

            paths = discover_app_paths(
                package,
                environ={"JJZERO_DATA_ROOT": str(root / "data")},
                frozen=True,
                executable=install / "JJZero Audio.exe",
                source_root=source,
            )

            self.assertEqual(paths.workspace_root, (install / "workspace").resolve())
            self.assertEqual(paths.legacy_root, install.resolve())
            self.assertEqual(paths.workspace_source, "legacy_install")


if __name__ == "__main__":
    unittest.main()
