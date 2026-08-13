from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongItem, SongLibrary, sort_song_items
from jang_app.services.song_package import SongPackageStore


class SongLibraryTests(unittest.TestCase):
    def test_song_items_can_be_sorted_by_creation_time_and_name(self) -> None:
        items = [
            SongItem(
                "b",
                Path("beta.wav"),
                title_override="Beta",
                created_at="2026-01-02T00:00:00+00:00",
            ),
            SongItem(
                "a",
                Path("alpha.wav"),
                title_override="alpha",
                created_at="2026-01-03T00:00:00+00:00",
            ),
            SongItem(
                "c",
                Path("charlie.wav"),
                title_override="Charlie",
                created_at="2026-01-01T00:00:00+00:00",
            ),
        ]

        self.assertEqual([item.id for item in sort_song_items(items, "newest")], ["a", "b", "c"])
        self.assertEqual([item.id for item in sort_song_items(items, "oldest")], ["c", "b", "a"])
        self.assertEqual([item.id for item in sort_song_items(items, "name_asc")], ["a", "b", "c"])
        self.assertEqual([item.id for item in sort_song_items(items, "name_desc")], ["c", "b", "a"])

    def test_legacy_sources_and_outputs_merge_into_one_song_without_modifying_legacy_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "downloads" / "good_old_days_abc123.m4a"
            source.parent.mkdir()
            source.write_bytes(b"source")
            legacy_file = project / "settings" / "song_library.json"
            legacy_file.parent.mkdir()
            legacy_file.write_text(json.dumps({"paths": [str(source)]}), encoding="utf-8")
            original_legacy = legacy_file.read_bytes()
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(legacy_file, store)
            matched = _sound_set(project, "Good Old Days [abc123]")
            unmatched = _sound_set(project, "Unrelated Legacy Output")

            library.add_output_sets([matched, unmatched])
            items = library.items()

            self.assertEqual(len(items), 2)
            source_item = next(item for item in items if item.kind == "source")
            recovery_item = next(item for item in items if item.kind == "output")
            self.assertEqual(source_item.output_job_dir, matched.job_dir.resolve())
            self.assertEqual(recovery_item.output_job_dir, unmatched.job_dir.resolve())
            self.assertNotEqual(source_item.path, source.resolve())
            self.assertEqual(source_item.path.read_bytes(), source.read_bytes())
            self.assertEqual(legacy_file.read_bytes(), original_legacy)

    def test_youtube_metadata_rename_and_remove_are_owned_by_song_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "download.m4a"
            source.write_bytes(b"youtube")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)

            added = library.add_youtube_audio(source, "Video Title", "https://example.test/watch?v=1")

            self.assertIsNotNone(added)
            self.assertEqual(added.title, "Video Title")
            self.assertEqual(added.source_type, "youtube")
            self.assertEqual(added.source_url, "https://example.test/watch?v=1")
            self.assertTrue(library.rename_item(added.id, "Renamed"))
            self.assertEqual(library.items()[0].title, "Renamed")
            self.assertTrue(library.remove_item(added.id))
            self.assertEqual(library.items(), [])
            removed = store.require(added.id, include_removed=True)
            self.assertTrue(removed.removed)
            self.assertIsNone(removed.source_path)
            self.assertEqual(
                {item.name for item in removed.folder.iterdir()},
                {"song.json"},
            )
            self.assertTrue(source.is_file())

    def test_initialization_purges_files_left_by_legacy_library_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Removed Song")
            leftover = package.folder / "04_exports" / "leftover.wav"
            leftover.write_bytes(b"leftover")
            store.set_removed(package.song_id, True)

            library = SongLibrary(project / "missing.json", store)

            self.assertEqual(library.items(), [])
            self.assertFalse(leftover.exists())
            self.assertEqual(
                {item.name for item in package.folder.iterdir()},
                {"song.json"},
            )

    def test_managed_vocal_output_is_registered_and_loaded_from_song_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            output_root = library.vocal_separation_root(song.id)
            job_dir = output_root / "htdemucs" / source.stem
            job_dir.mkdir(parents=True)
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            (job_dir / "vocals_rvc_voice_pitch_p0_noindex_rmvpe.wav").write_bytes(b"converted")

            updated = library.register_output(song.id, job_dir, "htdemucs")
            sound_sets = library.output_sound_sets()

            self.assertEqual(updated.output_job_dir, job_dir.resolve())
            self.assertEqual(len(sound_sets), 1)
            self.assertEqual(sound_sets[0].label, "source / htdemucs")
            self.assertEqual(sound_sets[0].job_dir, job_dir.resolve())
            self.assertEqual(len(sound_sets[0].converted_vocal_paths), 1)

            versions = library.vocal_versions(song.id)
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].job_dir, job_dir.resolve())
            self.assertEqual(versions[0].active_converted_path, versions[0].converted_vocal_paths[0])

    def test_scanned_output_sound_set_is_reused_without_reloading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            sound_set = _sound_set(project, source.stem)

            library.add_output_sets([sound_set])

            self.assertEqual(library.items()[0].output_job_dir, sound_set.job_dir.resolve())
            with patch(
                "jang_app.services.song_library.load_output_sound_set",
                side_effect=AssertionError("output sound set should come from cache"),
            ):
                sound_sets = library.output_sound_sets()

            self.assertEqual(len(sound_sets), 1)
            self.assertEqual(sound_sets[0].job_dir, sound_set.job_dir.resolve())

    def test_vocal_versions_reuse_cached_sound_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            output_root = library.vocal_separation_root(song.id)
            job_dir = output_root / "htdemucs" / source.stem
            job_dir.mkdir(parents=True)
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            library.register_output(song.id, job_dir, "htdemucs")

            with patch(
                "jang_app.services.song_library.load_output_sound_set",
                side_effect=AssertionError("vocal version should reuse cached sound set"),
            ):
                versions = library.vocal_versions(song.id)

            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].job_dir, job_dir.resolve())

    def test_selecting_output_version_updates_song_active_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            first = project / "first"
            second = project / "second"
            first.mkdir()
            second.mkdir()
            library.register_output(song.id, first, "First")
            library.register_output(song.id, second, "Second")

            activated = library.activate_output(first)

            self.assertIsNotNone(activated)
            self.assertEqual(activated.output_job_dir, first.resolve())
            self.assertEqual(library.items()[0].output_job_dir, first.resolve())

    def test_output_only_song_can_recover_its_original_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            sound_set = _sound_set(project, "Recovered Song")
            source = project / "original.wav"
            source.write_bytes(b"original")
            library.add_output_sets([sound_set])
            recovered = library.items()[0]

            attached = library.attach_source(recovered.id, source)

            self.assertEqual(attached.id, recovered.id)
            self.assertEqual(attached.kind, "source")
            self.assertNotEqual(attached.path, source.resolve())
            self.assertEqual(attached.path.read_bytes(), source.read_bytes())
            self.assertEqual(attached.output_job_dir, sound_set.job_dir.resolve())

    def test_recovering_a_known_source_merges_outputs_without_a_duplicate_song(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            source = project / "original.wav"
            source.write_bytes(b"original")
            original = library.add_paths([source])[0]
            sound_set = _sound_set(project, "Unmatched Output")
            recovery = store.create_output_recovery(
                "Unmatched Output",
                sound_set.job_dir,
                sound_set.label,
            )

            attached = library.attach_source(recovery.song_id, source)

            self.assertEqual(attached.id, original.id)
            self.assertEqual(attached.output_job_dir, sound_set.job_dir.resolve())
            self.assertEqual([item.id for item in library.items()], [original.id])

    def test_missing_managed_source_can_be_relinked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            source = project / "original.wav"
            source.write_bytes(b"original")
            song = library.add_paths([source])[0]
            song.path.unlink()

            relinked = library.attach_source(song.id, source)

            self.assertTrue(relinked.path.is_file())
            self.assertEqual(relinked.path.read_bytes(), b"original")

    def test_converted_selection_and_output_detach_are_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            job_dir = project / "output"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            first = job_dir / "vocals_rvc_first.wav"
            second = job_dir / "vocals_rvc_second.wav"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            library.register_output(song.id, job_dir, "Version")

            updated = library.activate_converted_output(job_dir, second)
            selected_path = store.require(song.id).outputs[0].active_converted_path
            detached = library.detach_output(job_dir)

            self.assertIsNotNone(updated)
            self.assertEqual(selected_path, second.resolve())
            self.assertIsNotNone(detached)
            self.assertIsNone(detached.output_job_dir)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

            reloaded = SongLibrary(
                project / "missing.json",
                SongPackageStore(project / "workspace" / "library" / "songs", project),
            )
            reloaded.add_output_sets(
                [OutputSoundSet("Version", job_dir, job_dir / "vocals.wav", job_dir / "no_vocals.wav", (first, second))]
            )
            self.assertEqual(reloaded.vocal_versions(song.id), ())

    def test_detaching_output_clears_cached_sound_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            library = SongLibrary(project / "missing.json", store)
            song = library.add_paths([source])[0]
            job_dir = project / "output"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            library.register_output(song.id, job_dir, "Version")

            library.detach_output(job_dir)

            self.assertNotIn(job_dir.resolve(), library._output_sound_sets_by_job_dir)


def _sound_set(project: Path, name: str) -> OutputSoundSet:
    job_dir = project / "output" / "separations" / "htdemucs" / name
    job_dir.mkdir(parents=True)
    vocals = job_dir / "vocals.wav"
    instrumental = job_dir / "no_vocals.wav"
    vocals.write_bytes(b"vocals")
    instrumental.write_bytes(b"instrumental")
    return OutputSoundSet(name, job_dir, vocals, instrumental, ())


if __name__ == "__main__":
    unittest.main()
