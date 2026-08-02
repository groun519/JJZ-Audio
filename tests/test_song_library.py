from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore


class SongLibraryTests(unittest.TestCase):
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
            self.assertTrue(library.rename_item(added.id, "Renamed"))
            self.assertEqual(library.items()[0].title, "Renamed")
            self.assertTrue(library.remove_item(added.id))
            self.assertEqual(library.items(), [])
            self.assertTrue(store.require(added.id, include_removed=True).removed)


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
