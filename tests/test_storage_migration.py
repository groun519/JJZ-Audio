from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.storage_migration import (
    StorageMigrationError,
    migrate_storage,
    plan_storage_migration,
    recover_storage_migrations,
)
from jang_app.services.initial_setup import build_custom_storage_layout


class StorageMigrationTests(unittest.TestCase):
    def test_managed_storage_change_copies_all_components_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_root = root / "C-drive" / "JJZero Audio"
            target_root = root / "D-drive" / "JJZero Audio"
            paths = _managed_paths(root, current_root)

            source_audio = paths.workspace_root / "library" / "songs" / "song-a" / "source.wav"
            song_manifest = source_audio.with_name("song.json")
            source_audio.parent.mkdir(parents=True)
            source_audio.write_bytes(b"audio")
            song_manifest.write_text(
                json.dumps(
                    {
                        "source_path": str(source_audio),
                        "output_path": str(paths.output_root / "mix.wav"),
                        "runtime_model": str(paths.runtime_root / "rvc" / "weights" / "voice.pth"),
                        "project_output": "@project/Output/mix.wav",
                    }
                ),
                encoding="utf-8",
            )
            model_manifest = paths.workspace_root / "models" / "library" / "voice" / "model.json"
            model_manifest.parent.mkdir(parents=True)
            model_manifest.write_text(
                json.dumps(
                    {
                        "checkpoint": str(
                            paths.runtime_root / "rvc" / "weights" / "voice.pth"
                        )
                    }
                ),
                encoding="utf-8",
            )
            output_file = paths.output_root / "mix.wav"
            output_file.parent.mkdir(parents=True)
            output_file.write_bytes(b"mix")
            runtime_file = paths.runtime_root / "rvc" / "weights" / "voice.pth"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_bytes(b"model")
            cache_file = paths.cache_dir / "runtime" / "package.zip"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"cache")

            app_settings = paths.settings_dir / "app_settings.json"
            app_settings.write_text(
                json.dumps(
                    {
                        "output_root": str(paths.output_root),
                        "rvc_root": str(paths.runtime_root / "rvc"),
                    }
                ),
                encoding="utf-8",
            )

            plan = plan_storage_migration(paths, target_root)
            self.assertEqual(
                tuple(component.name for component in plan.components),
                ("Data", "Output", "Runtime"),
            )
            self.assertTrue(plan.cache_reset)

            configured = migrate_storage(plan)
            rediscovered = _discover_paths(root)

            self.assertEqual(configured.storage_root, target_root.resolve())
            self.assertEqual(rediscovered.storage_root, target_root.resolve())
            self.assertEqual(rediscovered.workspace_root, (target_root / "Data").resolve())
            self.assertEqual(rediscovered.output_root, (target_root / "Output").resolve())
            self.assertEqual(rediscovered.runtime_root, (target_root / "Runtime").resolve())
            self.assertEqual(rediscovered.cache_dir, (target_root / "Cache").resolve())
            self.assertTrue(
                (
                    target_root / "Data" / source_audio.relative_to(paths.workspace_root)
                ).is_file()
            )
            self.assertTrue(
                (
                    target_root / "Data" / model_manifest.relative_to(paths.workspace_root)
                ).is_file()
            )
            self.assertEqual((target_root / "Output" / "mix.wav").read_bytes(), b"mix")
            self.assertEqual(
                (target_root / "Runtime" / "rvc" / "weights" / "voice.pth").read_bytes(),
                b"model",
            )
            self.assertTrue((target_root / "Cache").is_dir())
            self.assertFalse((target_root / "Cache" / "runtime" / "package.zip").exists())

            migrated_manifest = json.loads(
                (
                    target_root
                    / "Data"
                    / song_manifest.relative_to(paths.workspace_root)
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                Path(migrated_manifest["source_path"]),
                target_root / "Data" / source_audio.relative_to(paths.workspace_root),
            )
            self.assertEqual(
                Path(migrated_manifest["output_path"]),
                target_root / "Output" / "mix.wav",
            )
            self.assertEqual(
                Path(migrated_manifest["runtime_model"]),
                target_root / "Runtime" / "rvc" / "weights" / "voice.pth",
            )
            self.assertEqual(migrated_manifest["project_output"], "@project/Output/mix.wav")
            migrated_settings = json.loads(app_settings.read_text(encoding="utf-8"))
            self.assertEqual(Path(migrated_settings["output_root"]), target_root / "Output")
            self.assertEqual(Path(migrated_settings["rvc_root"]), target_root / "Runtime" / "rvc")

            self.assertTrue(source_audio.is_file())
            self.assertTrue(model_manifest.is_file())
            self.assertTrue(output_file.is_file())
            self.assertTrue(runtime_file.is_file())
            self.assertTrue(cache_file.is_file())
            self.assertFalse(plan_storage_migration(rediscovered, target_root).required)

    def test_v1_layout_is_copied_verified_and_switched_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _legacy_paths(root)
            song_manifest = paths.workspace_root / "library" / "songs" / "song-a" / "song.json"
            song_manifest.parent.mkdir(parents=True)
            song_manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "song-a",
                        "title": "Song",
                        "created_at": "2026-08-06T00:00:00+00:00",
                        "source": None,
                        "vocal": {
                            "active_output_id": "",
                            "detached_outputs": [],
                            "outputs": [],
                        },
                        "legacy_path": str(paths.workspace_root / "legacy.wav"),
                        "project_workspace_path": "@project/workspace/legacy.wav",
                        "project_output_path": "@project/output/separations/mix.wav",
                        "project_external_path": "@project/custom/reference.wav",
                    }
                ),
                encoding="utf-8",
            )
            output_file = paths.output_root / "mix.wav"
            output_file.parent.mkdir(parents=True)
            output_file.write_bytes(b"mix")
            runtime_file = paths.runtime_root / "rvc" / "runtime.bin"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_bytes(b"runtime")
            cache_file = paths.cache_dir / "download.pkg"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"cache")
            app_settings = paths.settings_dir / "app_settings.json"
            app_settings.write_text(
                json.dumps(
                    {
                        "output_root": str(paths.output_root / "separations"),
                        "rvc": {"root": str(paths.runtime_root / "rvc")},
                    }
                ),
                encoding="utf-8",
            )
            target = root / "portable"
            progress: list[tuple[str, int]] = []

            plan = plan_storage_migration(paths, target)
            configured = migrate_storage(plan, lambda stage, value: progress.append((stage, value)))

            self.assertTrue(song_manifest.is_file())
            self.assertTrue(output_file.is_file())
            self.assertTrue(runtime_file.is_file())
            self.assertTrue(cache_file.is_file())
            self.assertTrue(
                (
                    target / "Data" / song_manifest.relative_to(paths.workspace_root)
                ).is_file()
            )
            self.assertTrue((target / "Output" / "mix.wav").is_file())
            self.assertTrue((target / "Runtime" / "rvc" / "runtime.bin").is_file())
            self.assertTrue((target / "Cache").is_dir())
            self.assertFalse((target / "Cache" / "download.pkg").exists())
            self.assertEqual(configured.storage_version, 3)
            self.assertEqual(configured.storage_root, target.resolve())
            storage = json.loads(paths.storage_file.read_text(encoding="utf-8"))
            self.assertEqual(storage["version"], 3)
            migrated_manifest = json.loads(
                (target / "Data" / song_manifest.relative_to(paths.workspace_root)).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                Path(migrated_manifest["legacy_path"]),
                target / "Data" / "legacy.wav",
            )
            self.assertEqual(
                migrated_manifest["project_workspace_path"],
                "@project/Data/legacy.wav",
            )
            self.assertEqual(
                migrated_manifest["project_output_path"],
                "@project/Output/separations/mix.wav",
            )
            self.assertEqual(
                Path(migrated_manifest["project_external_path"]),
                paths.workspace_anchor / "custom" / "reference.wav",
            )
            migrated_settings = json.loads(app_settings.read_text(encoding="utf-8"))
            self.assertEqual(
                Path(migrated_settings["output_root"]),
                target / "Output" / "separations",
            )
            self.assertEqual(
                Path(migrated_settings["rvc"]["root"]),
                target / "Runtime" / "rvc",
            )
            self.assertEqual(progress[-1], ("Storage ready", 100))

    def test_existing_target_files_block_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _legacy_paths(root)
            source = paths.workspace_root / "source.txt"
            source.parent.mkdir(parents=True)
            source.write_text("source", encoding="utf-8")
            target = root / "portable"
            conflicting = target / "Data" / "existing.txt"
            conflicting.parent.mkdir(parents=True)
            conflicting.write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(StorageMigrationError, "already contains files"):
                plan_storage_migration(paths, target)

    def test_custom_layout_moves_only_changed_output_and_resets_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _managed_paths(root, root / "current")
            output = paths.output_root / "mix.wav"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"mix")
            cache = paths.cache_dir / "runtime.zip"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"cache")
            configured = build_custom_storage_layout(
                paths,
                workspace_root=paths.workspace_root,
                output_root=root / "external-output",
                runtime_root=paths.runtime_root,
                cache_root=root / "new-cache",
            )

            plan = plan_storage_migration(paths, configured)
            result = migrate_storage(plan)

            self.assertEqual(tuple(item.name for item in plan.components), ("Output",))
            self.assertTrue(plan.cache_reset)
            self.assertEqual((result.output_root / "mix.wav").read_bytes(), b"mix")
            self.assertTrue(result.cache_dir.is_dir())
            self.assertFalse((result.cache_dir / "runtime.zip").exists())
            self.assertTrue(cache.is_file())

    def test_cancelled_copy_preserves_source_and_records_recoverable_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _managed_paths(root, root / "current")
            source = paths.workspace_root / "song.wav"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"audio")
            configured = build_custom_storage_layout(
                paths,
                workspace_root=root / "new-data",
                output_root=paths.output_root,
                runtime_root=paths.runtime_root,
                cache_root=paths.cache_dir,
            )
            plan = plan_storage_migration(paths, configured)

            with self.assertRaisesRegex(StorageMigrationError, "cancelled"):
                migrate_storage(plan, cancelled=lambda: True)

            self.assertTrue(source.is_file())
            journal = paths.data_root / "migrations" / f"storage-relocation-{plan.transaction_id}.json"
            self.assertTrue(journal.is_file())
            recovered = recover_storage_migrations(paths)
            self.assertEqual(recovered, (journal,))

    def test_checks_free_space_on_the_changed_component_drive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _managed_paths(root, root / "current")
            output = paths.output_root / "large.wav"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"audio")
            configured = build_custom_storage_layout(
                paths,
                workspace_root=paths.workspace_root,
                output_root=Path("D:/JJZero Audio/Output"),
                runtime_root=paths.runtime_root,
                cache_root=paths.cache_dir,
            )

            with (
                patch(
                    "jang_app.services.storage_migration.shutil.disk_usage",
                    return_value=SimpleNamespace(free=1),
                ),
                self.assertRaisesRegex(StorageMigrationError, "enough free space"),
            ):
                plan_storage_migration(paths, configured)


def _legacy_paths(root: Path):
    source = root / "source"
    package = source / "src" / "jang_app"
    package.mkdir(parents=True)
    data_root = root / "local"
    media_root = root / "legacy-media"
    settings = data_root / "settings"
    settings.mkdir(parents=True)
    (settings / "storage.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workspace_root": str(media_root / "workspace"),
                "workspace_anchor": str(media_root),
            }
        ),
        encoding="utf-8",
    )
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(data_root)},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=source,
    )


def _managed_paths(root: Path, storage_root: Path):
    settings = root / "local" / "settings"
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
    return _discover_paths(root)


def _discover_paths(root: Path):
    source = root / "source"
    package = source / "src" / "jang_app"
    package.mkdir(parents=True, exist_ok=True)
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "local")},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=source,
    )


if __name__ == "__main__":
    unittest.main()
