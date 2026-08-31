from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jang_app.services.managed_transaction import (
    ManagedPathTransaction,
    recover_managed_transactions,
)
from jang_app.services.song_package import SongPackageStore


class SongPackageStoreTests(unittest.TestCase):
    def test_startup_recovery_removes_interrupted_song_import_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)

            def interrupt_copy(_source, target, *_args, **_kwargs):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"partial")
                raise SystemExit

            with patch(
                "jang_app.services.song_package.copy_file_atomic",
                side_effect=interrupt_copy,
            ):
                with self.assertRaises(SystemExit):
                    store.import_audio(source, title="Interrupted Song")

            reports = recover_managed_transactions(root)

            self.assertEqual(reports[0].action, "rolled_back")
            self.assertEqual(SongPackageStore(root, project).packages(), [])
            self.assertFalse((root / ".jjzero-transactions").exists())

    def test_unchanged_manifests_are_loaded_once_and_reused_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            created, _was_created = SongPackageStore(root, project).import_audio(
                source,
                title="Song",
            )
            store = SongPackageStore(root, project)

            with patch.object(
                store,
                "_load_manifest",
                wraps=store._load_manifest,
            ) as load_manifest:
                first = store.packages()
                renamed = store.rename(created.song_id, "Renamed Song")
                required = store.require(created.song_id)

            self.assertEqual(load_manifest.call_count, 1)
            self.assertEqual(first[0].title, "Song")
            self.assertEqual(required, renamed)

    def test_external_manifest_change_invalidates_cached_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _was_created = store.import_audio(source, title="Song")
            self.assertEqual(store.require(package.song_id).title, "Song")

            manifest_path = package.folder / "song.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["title"] = "Externally Renamed Song"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(
                store.require(package.song_id).title,
                "Externally Renamed Song",
            )

    def test_import_creates_self_contained_song_stages_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "incoming" / "voice.m4a"
            source.parent.mkdir()
            source.write_bytes(b"original audio")
            original = source.read_bytes()
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )

            package, created = store.import_audio(
                source,
                title="My Song",
                source_type="youtube",
                source_url="url",
            )
            duplicate, duplicate_created = store.import_audio(
                source,
                title="Ignored",
            )

            self.assertTrue(created)
            self.assertFalse(duplicate_created)
            self.assertEqual(duplicate.song_id, package.song_id)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(package.source_path.read_bytes(), original)
            self.assertTrue((package.folder / "01_source" / "video").is_dir())
            self.assertTrue((package.folder / "02_vocal").is_dir())
            self.assertTrue((package.folder / "03_studio").is_dir())
            self.assertTrue((package.folder / "04_exports").is_dir())
            manifest = json.loads(
                (package.folder / "song.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["source"]["audio"],
                "01_source/audio/source.m4a",
            )
            self.assertEqual(manifest["source"]["type"], "youtube")
            self.assertEqual(manifest["source"]["url"], "url")
            self.assertRegex(package.folder.name, r"^s_[0-9a-f]{16}$")
            self.assertNotIn("My Song", package.folder.name)

    def test_failed_import_does_not_leave_an_invisible_source_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)

            with patch.object(
                store,
                "_save",
                side_effect=OSError("manifest unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "manifest unavailable"):
                    store.import_audio(source, title="Song")

            self.assertEqual(SongPackageStore(root, project).packages(), [])
            self.assertFalse(any(root.glob("s_*")))
            self.assertFalse((root / ".jjzero-imports").exists())

    def test_failed_source_attachment_restores_output_only_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            output = project / "output"
            output.mkdir()
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)
            package = store.create_output_recovery("Recovered", output, "Output")

            with patch.object(
                store,
                "_save",
                side_effect=OSError("manifest unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "manifest unavailable"):
                    store.attach_source(package.song_id, source)

            restored = SongPackageStore(root, project).require(package.song_id)
            self.assertIsNone(restored.source_path)
            self.assertEqual(restored.outputs, package.outputs)
            self.assertFalse(
                (package.folder / "01_source" / "audio" / "source.wav").exists()
            )

    def test_output_reference_uses_project_relative_path_and_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            job_dir = project / "output" / "separations" / "song"
            job_dir.mkdir(parents=True)
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")

            store.attach_output(package.song_id, job_dir, "htdemucs/song")

            loaded = store.require(package.song_id)
            self.assertEqual(loaded.active_output.job_dir, job_dir.resolve())
            manifest = json.loads(
                (loaded.folder / "song.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["vocal"]["outputs"][0]["job_dir"],
                "@project/output/separations/song",
            )

    def test_concurrent_output_registration_preserves_every_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            creator = SongPackageStore(root, project)
            package, _created = creator.import_audio(source, title="Song")
            outputs = tuple(
                project / "outputs" / f"run-{index}" for index in range(16)
            )
            for output in outputs:
                output.mkdir(parents=True)

            def register(index: int) -> None:
                SongPackageStore(root, project).attach_output(
                    package.song_id,
                    outputs[index],
                    f"Run {index}",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                tuple(executor.map(register, range(len(outputs))))

            restored = SongPackageStore(root, project).require(package.song_id)
            self.assertEqual(
                {output.job_dir for output in restored.outputs},
                {path.resolve() for path in outputs},
            )

    def test_concurrent_same_source_import_creates_one_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"

            def import_source(_index: int):
                return SongPackageStore(root, project).import_audio(
                    source,
                    title="Song",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(executor.map(import_source, range(16)))

            self.assertEqual(sum(created for _package, created in results), 1)
            self.assertEqual(len(SongPackageStore(root, project).packages()), 1)

    def test_vocal_separation_root_is_owned_by_source_song(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")

            output_root = store.vocal_separation_root(package.song_id)

            self.assertEqual(
                output_root,
                package.folder / "02_vocal" / "separations",
            )
            self.assertTrue(output_root.is_dir())

    def test_each_separation_run_receives_a_unique_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")

            first = store.create_vocal_separation_run(package.song_id)
            second = store.create_vocal_separation_run(package.song_id)

            self.assertNotEqual(first, second)
            self.assertEqual(
                first.parent,
                package.folder / "02_vocal" / "separations",
            )
            self.assertEqual(second.parent, first.parent)
            self.assertRegex(first.name, r"^r_[0-9a-f]{12}$")
            self.assertRegex(second.name, r"^r_[0-9a-f]{12}$")

    def test_legacy_title_named_package_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)
            package, _created = store.import_audio(source, title="Legacy Song")
            legacy_folder = root / "Legacy Song__12345678"
            package.folder.rename(legacy_folder)

            loaded = SongPackageStore(root, project).require(package.song_id)

            self.assertEqual(loaded.folder, legacy_folder.resolve())
            self.assertEqual(loaded.title, "Legacy Song")
            self.assertTrue(loaded.source_path.is_file())

    def test_output_version_can_be_activated_without_reordering_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")
            first = project / "first"
            second = project / "second"
            first.mkdir()
            second.mkdir()
            store.attach_output(package.song_id, first, "First")
            latest = store.attach_output(package.song_id, second, "Second")

            activated = store.activate_output(package.song_id, first)

            self.assertEqual(latest.active_output.job_dir, second.resolve())
            self.assertEqual(activated.active_output.job_dir, first.resolve())
            self.assertEqual(
                [item.job_dir for item in activated.outputs],
                [item.job_dir for item in latest.outputs],
            )

    def test_converted_selection_persists_and_detach_keeps_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            job_dir = project / "output"
            job_dir.mkdir()
            converted = job_dir / "vocals_rvc_test.wav"
            converted.write_bytes(b"converted")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")
            store.attach_output(package.song_id, job_dir, "Version")

            selected = store.activate_converted_output(
                package.song_id,
                job_dir,
                converted,
            )
            detached = store.detach_output(package.song_id, job_dir)

            self.assertEqual(
                selected.active_output.active_converted_path,
                converted.resolve(),
            )
            self.assertEqual(detached.outputs, ())
            self.assertTrue(converted.is_file())

    def test_remove_managed_data_deletes_package_files_but_preserves_external_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            external_output = project / "legacy-output"
            external_output.mkdir()
            (external_output / "vocals.wav").write_bytes(b"external")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")
            store.attach_output(package.song_id, external_output, "Legacy")
            (package.folder / "02_vocal" / "managed.wav").write_bytes(b"managed")
            (package.folder / "03_studio" / "session.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (package.folder / "04_exports" / "mix.wav").write_bytes(b"mix")

            removed = store.remove_managed_data(package.song_id)

            self.assertTrue(removed.removed)
            self.assertIsNone(removed.source_path)
            self.assertEqual(removed.outputs, ())
            self.assertTrue((package.folder / "song.json").is_file())
            self.assertEqual(
                {item.name for item in package.folder.iterdir()},
                {"song.json"},
            )
            self.assertTrue((external_output / "vocals.wav").is_file())
            self.assertIn(
                external_output.resolve(),
                removed.detached_output_dirs,
            )
            self.assertTrue(source.is_file())

    def test_partial_delete_staging_failure_restores_every_song_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)
            package, _created = store.import_audio(source, title="Song")
            vocal = package.folder / "02_vocal" / "keep.wav"
            vocal.write_bytes(b"vocal")
            original_stage = ManagedPathTransaction.stage

            def fail_vocal_stage(transaction, path, label):
                if Path(path).name == "02_vocal":
                    raise OSError("vocal folder busy")
                return original_stage(transaction, path, label)

            with patch.object(
                ManagedPathTransaction,
                "stage",
                new=fail_vocal_stage,
            ):
                with self.assertRaisesRegex(OSError, "vocal folder busy"):
                    store.remove_managed_data(package.song_id)

            restored = SongPackageStore(root, project).require(package.song_id)
            self.assertFalse(restored.removed)
            self.assertEqual(restored.source_path.read_bytes(), b"audio")
            self.assertEqual(vocal.read_bytes(), b"vocal")

    def test_delete_manifest_failure_restores_staged_song_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)
            package, _created = store.import_audio(source, title="Song")
            export = package.folder / "04_exports" / "mix.wav"
            export.write_bytes(b"mix")

            with patch.object(
                store,
                "_save",
                side_effect=OSError("manifest unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "manifest unavailable"):
                    store.remove_managed_data(package.song_id)

            restored = SongPackageStore(root, project).require(package.song_id)
            self.assertFalse(restored.removed)
            self.assertTrue(restored.source_path.is_file())
            self.assertEqual(export.read_bytes(), b"mix")

    def test_startup_recovery_restores_song_after_interrupted_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            root = project / "workspace" / "library" / "songs"
            store = SongPackageStore(root, project)
            package, _created = store.import_audio(source, title="Song")
            export = package.folder / "04_exports" / "mix.wav"
            export.write_bytes(b"mix")

            with patch.object(store, "_save", side_effect=SystemExit):
                with self.assertRaises(SystemExit):
                    store.remove_managed_data(package.song_id)

            reports = recover_managed_transactions(root)
            restored = SongPackageStore(root, project).require(package.song_id)
            self.assertEqual(reports[0].action, "rolled_back")
            self.assertTrue(restored.source_path.is_file())
            self.assertEqual(export.read_bytes(), b"mix")

    def test_reimport_after_managed_data_removal_restores_source_without_old_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")
            (package.folder / "02_vocal" / "old.wav").write_bytes(b"old")
            store.remove_managed_data(package.song_id)

            restored, created = store.import_audio(source, title="Ignored")

            self.assertTrue(created)
            self.assertEqual(restored.song_id, package.song_id)
            self.assertFalse(restored.removed)
            self.assertIsNotNone(restored.source_path)
            self.assertTrue(restored.source_path.is_file())
            self.assertEqual(restored.source_path.read_bytes(), source.read_bytes())
            self.assertFalse((restored.folder / "02_vocal" / "old.wav").exists())
            self.assertEqual(restored.outputs, ())

    def test_purge_legacy_removed_data_cleans_old_soft_deleted_packages_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(
                project / "workspace" / "library" / "songs",
                project,
            )
            package, _created = store.import_audio(source, title="Song")
            (package.folder / "04_exports" / "old-mix.wav").write_bytes(b"mix")
            store.set_removed(package.song_id, True)

            first_count = store.purge_legacy_removed_data()
            second_count = store.purge_legacy_removed_data()
            removed = store.require(package.song_id, include_removed=True)

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)
            self.assertIsNone(removed.source_path)
            self.assertEqual(
                {item.name for item in removed.folder.iterdir()},
                {"song.json"},
            )


if __name__ == "__main__":
    unittest.main()
