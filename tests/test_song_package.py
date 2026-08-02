from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.song_package import SongPackageStore


class SongPackageStoreTests(unittest.TestCase):
    def test_import_creates_self_contained_song_stages_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "incoming" / "voice.m4a"
            source.parent.mkdir()
            source.write_bytes(b"original audio")
            original = source.read_bytes()
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)

            package, created = store.import_audio(source, title="My Song", source_type="youtube", source_url="url")
            duplicate, duplicate_created = store.import_audio(source, title="Ignored")

            self.assertTrue(created)
            self.assertFalse(duplicate_created)
            self.assertEqual(duplicate.song_id, package.song_id)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(package.source_path.read_bytes(), original)
            self.assertTrue((package.folder / "01_source" / "video").is_dir())
            self.assertTrue((package.folder / "02_vocal").is_dir())
            self.assertTrue((package.folder / "03_studio").is_dir())
            self.assertTrue((package.folder / "04_exports").is_dir())
            manifest = json.loads((package.folder / "song.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["source"]["audio"],
                f"01_source/audio/voice__{package.song_id[-8:]}.m4a",
            )
            self.assertEqual(manifest["source"]["type"], "youtube")
            self.assertEqual(manifest["source"]["url"], "url")

    def test_output_reference_uses_project_relative_path_and_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            job_dir = project / "output" / "separations" / "song"
            job_dir.mkdir(parents=True)
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")

            store.attach_output(package.song_id, job_dir, "htdemucs/song")

            loaded = store.require(package.song_id)
            self.assertEqual(loaded.active_output.job_dir, job_dir.resolve())
            manifest = json.loads((loaded.folder / "song.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["vocal"]["outputs"][0]["job_dir"],
                "@project/output/separations/song",
            )

    def test_vocal_separation_root_is_owned_by_source_song(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")

            output_root = store.vocal_separation_root(package.song_id)

            self.assertEqual(output_root, package.folder / "02_vocal" / "separations")
            self.assertTrue(output_root.is_dir())

    def test_each_separation_run_receives_a_unique_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")

            first = store.create_vocal_separation_run(package.song_id)
            second = store.create_vocal_separation_run(package.song_id)

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, package.folder / "02_vocal" / "separations")
            self.assertEqual(second.parent, first.parent)

    def test_output_version_can_be_activated_without_reordering_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"audio")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
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
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")
            store.attach_output(package.song_id, job_dir, "Version")

            selected = store.activate_converted_output(package.song_id, job_dir, converted)
            detached = store.detach_output(package.song_id, job_dir)

            self.assertEqual(selected.active_output.active_converted_path, converted.resolve())
            self.assertEqual(detached.outputs, ())
            self.assertTrue(converted.is_file())


if __name__ == "__main__":
    unittest.main()
