from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioExportError
from jang_app.services.song_export import (
    build_song_mix_sources,
    export_song_mix,
    list_song_audio_exports,
    song_audio_export_dir,
)
from jang_app.services.song_package import SongPackageStore
from jang_app.services.song_library import SongLibrary
from jang_app.services.studio_session import (
    StudioSession,
    StudioTrackState,
)


class SongExportTests(unittest.TestCase):
    def test_mix_sources_use_active_output_converted_version_and_studio_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            session = StudioSession(
                original_vocal=StudioTrackState(muted=True, volume_percent=40),
                instrumental=StudioTrackState(volume_percent=125),
                converted_vocal=StudioTrackState(volume_percent=200),
            )

            sources = build_song_mix_sources(package, session)

            self.assertEqual([source.label for source in sources], ["Instrumental", "Converted Vocal"])
            self.assertEqual([source.volume for source in sources], [1.25, 2.0])
            self.assertEqual(sources[1].path.name, "vocals_rvc_second.wav")

    def test_exports_are_unique_and_listed_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))

            def fake_export(_sources, output_path: Path, **_options) -> Path:
                output_path.write_bytes(b"mix")
                return output_path

            with patch("jang_app.services.song_export.export_mix", side_effect=fake_export):
                first = export_song_mix(package, StudioSession())
                second = export_song_mix(package, StudioSession())

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, song_audio_export_dir(package))
            records = list_song_audio_exports(package)
            self.assertEqual({record.path for record in records}, {first, second})
            self.assertTrue(all(record.size_bytes == 3 for record in records))

    def test_export_rejects_a_session_with_every_track_muted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            muted = StudioTrackState(muted=True)

            with self.assertRaises(AudioExportError):
                build_song_mix_sources(package, StudioSession(muted, muted, muted))

    def test_library_export_renders_the_saved_session_into_the_song_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            sf.write(source, np.full(800, 0.25, dtype=np.float32), 8000)
            store = SongPackageStore(root / "workspace" / "library" / "songs", root)
            package, _created = store.import_audio(source, title="Song")
            output_dir = root / "vocal-output"
            output_dir.mkdir()
            sf.write(output_dir / "vocals.wav", np.full(800, 0.5, dtype=np.float32), 8000)
            sf.write(output_dir / "no_vocals.wav", np.full(1600, 0.1, dtype=np.float32), 16000)
            store.attach_output(package.song_id, output_dir, "Run 01")
            library = SongLibrary(root / "legacy.json", store)
            library.save_studio_session(
                package.song_id,
                StudioSession(
                    original_vocal=StudioTrackState(muted=True),
                    instrumental=StudioTrackState(volume_percent=50),
                ),
            )

            exported = library.export_audio_mix(package.song_id)
            audio, sample_rate = sf.read(exported, dtype="float32")

            self.assertEqual(exported.parent, package.folder / "04_exports" / "audio")
            self.assertEqual(sample_rate, 16000)
            self.assertEqual(len(audio), 1600)
            self.assertAlmostEqual(float(np.max(audio)), 0.05, places=2)


def _package_with_output(root: Path):
    source = root / "source.wav"
    source.write_bytes(b"source")
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    package, _created = store.import_audio(source, title="Song")

    output_dir = root / "vocal-output"
    output_dir.mkdir()
    for name in ("vocals.wav", "no_vocals.wav", "vocals_rvc_first.wav", "vocals_rvc_second.wav"):
        (output_dir / name).write_bytes(name.encode("ascii"))
    package = store.attach_output(package.song_id, output_dir, "Run 01")
    return store.activate_converted_output(package.song_id, output_dir, output_dir / "vocals_rvc_second.wav")


if __name__ == "__main__":
    unittest.main()
