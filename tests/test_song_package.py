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


if __name__ == "__main__":
    unittest.main()
