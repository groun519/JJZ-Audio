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
    TRACK_CONVERTED_VOCAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioEffect,
    StudioSession,
    StudioTrack,
    StudioTrackState,
    StudioLevelMatchSettings,
    load_studio_session,
)
from jang_app.services.studio_assets import studio_sound_pool
from jang_app.services.video_source import VideoSourceStore
from jang_app.services.studio_timeline import move_studio_clip, set_studio_track_mix, trim_studio_clip


class SongExportTests(unittest.TestCase):
    def test_timeline_mix_source_keeps_clip_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            output_id = package.active_output.output_id
            effect = StudioEffect("fx-reverb", "reverb")
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-vocal",
                        "Original Vocal",
                        role=TRACK_ORIGINAL_VOCAL,
                        clips=(
                            StudioClip(
                                "vocal",
                                StudioAssetRef(output_id, TRACK_ORIGINAL_VOCAL),
                                0,
                                0,
                                1_000,
                                pitch_semitones=5,
                                effects=(effect,),
                            ),
                        ),
                    ),
                )
            )

            sources = build_song_mix_sources(package, session)

            self.assertEqual(sources[0].effects, (effect,))
            self.assertEqual(sources[0].pitch_semitones, 5)

    def test_level_match_resolves_original_vocal_from_the_same_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            output = package.active_output
            effect = StudioEffect(
                "fx-level",
                "level_match",
                level_match=StudioLevelMatchSettings(),
            )
            clip = StudioClip(
                "converted",
                StudioAssetRef(
                    output.output_id,
                    TRACK_CONVERTED_VOCAL,
                    "vocals_rvc_second.wav",
                ),
                0,
                0,
                1_000,
                effects=(effect,),
            )
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-converted",
                        "Converted Vocal",
                        role=TRACK_CONVERTED_VOCAL,
                        clips=(clip,),
                    ),
                )
            )

            source = build_song_mix_sources(package, session)[0]

            self.assertEqual(source.reference_path, (output.job_dir / "vocals.wav").resolve())

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

            def fake_export(_sources, output_path: Path, *_args, **_options) -> Path:
                output_path.write_bytes(b"mix")
                return output_path

            with patch("jang_app.services.song_export.export_final_audio_mix", side_effect=fake_export):
                first = export_song_mix(package, StudioSession())
                second = export_song_mix(package, StudioSession())

            self.assertNotEqual(first, second)
            self.assertEqual(first.name, "Song - Master WAV.wav")
            self.assertEqual(second.name, "Song - Master WAV (2).wav")
            self.assertEqual(first.parent, song_audio_export_dir(package))
            records = list_song_audio_exports(package)
            self.assertEqual({record.path for record in records}, {first, second})
            self.assertTrue(all(record.size_bytes == 3 for record in records))

    def test_legacy_timestamp_mix_is_renamed_when_exports_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            output_dir = song_audio_export_dir(package)
            output_dir.mkdir(parents=True)
            legacy = output_dir / "mix-20260806-160444.wav"
            legacy.write_bytes(b"mix")

            records = list_song_audio_exports(package)

            self.assertFalse(legacy.exists())
            self.assertEqual([record.path.name for record in records], ["Song - Audio Mix.wav"])

    def test_opus_exports_are_included_in_the_audio_export_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            output_dir = song_audio_export_dir(package)
            output_dir.mkdir(parents=True)
            opus = output_dir / "Song - Discord 10MB.ogg"
            opus.write_bytes(b"opus")

            records = list_song_audio_exports(package)

            self.assertEqual([record.path for record in records], [opus.resolve()])

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

    def test_timeline_export_applies_clip_trim_and_timeline_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            sf.write(source, np.full(16_000, 0.1, dtype=np.float32), 8_000)
            store = SongPackageStore(root / "workspace" / "library" / "songs", root)
            package, _created = store.import_audio(source, title="Song")
            output_dir = root / "vocal-output"
            output_dir.mkdir()
            sf.write(output_dir / "vocals.wav", np.full(16_000, 0.5, dtype=np.float32), 8_000)
            sf.write(output_dir / "no_vocals.wav", np.full(16_000, 0.1, dtype=np.float32), 8_000)
            package = store.attach_output(package.song_id, output_dir, "Run 01")
            session = load_studio_session(package)
            vocal_track = session.tracks[0]
            clip = vocal_track.clips[0]
            session = trim_studio_clip(
                session,
                clip.clip_id,
                source_start_ms=250,
                source_end_ms=1_250,
            )
            session = move_studio_clip(
                session,
                clip.clip_id,
                track_id=vocal_track.track_id,
                timeline_start_ms=500,
            )
            session = set_studio_track_mix(session, session.tracks[1].track_id, muted=True)

            output_path = root / "timeline.wav"
            from jang_app.services.audio_export import export_mix

            export_mix(build_song_mix_sources(package, session), output_path)
            audio, sample_rate = sf.read(output_path, dtype="float32")

            self.assertEqual(sample_rate, 8_000)
            self.assertEqual(len(audio), 12_000)
            self.assertAlmostEqual(float(np.max(np.abs(audio[:4_000]))), 0.0, places=3)
            self.assertAlmostEqual(float(np.max(audio[4_000:])), 0.5, places=2)

    def test_timeline_audio_mix_ignores_video_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_output(root)
            source_video = root / "reference.mp4"
            source_video.write_bytes(b"video")
            VideoSourceStore().import_file(package, source_video)
            video_asset = next(
                asset for asset in studio_sound_pool(package) if asset.reference.role == TRACK_VIDEO
            )
            output_id = package.active_output.output_id
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-video",
                        "Video",
                        role=TRACK_VIDEO,
                        clips=(StudioClip("video", video_asset.reference, 0, 0, 1_000),),
                    ),
                    StudioTrack(
                        "track-vocal",
                        "Original Vocal",
                        role=TRACK_ORIGINAL_VOCAL,
                        clips=(
                            StudioClip(
                                "vocal",
                                StudioAssetRef(output_id, TRACK_ORIGINAL_VOCAL),
                                0,
                                0,
                                1_000,
                            ),
                        ),
                    ),
                )
            )

            sources = build_song_mix_sources(package, session)

            self.assertEqual([source.path.name for source in sources], ["vocals.wav"])


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
