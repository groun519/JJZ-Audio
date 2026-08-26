from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.studio_realtime_audio import (
    prepare_studio_playback_audio,
    read_playback_audio,
)
from jang_app.services.studio_session import (
    StudioDelaySettings,
    StudioDistortionSettings,
    StudioEffect,
    StudioLevelMatchSettings,
    StudioReverbSettings,
)


class StudioRealtimeAudioTests(unittest.TestCase):
    def test_preview_reads_the_cached_pitch_render_for_a_shifted_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.wav"
            shifted_path = root / "shifted.wav"
            sf.write(source_path, np.full(44_100, 0.1, dtype=np.float32), 44_100)
            sf.write(shifted_path, np.full(44_100, 0.3, dtype=np.float32), 44_100)
            source = AudioMixSource(
                "Shifted",
                source_path,
                source_end_ms=1_000,
                pitch_semitones=12,
            )

            with patch(
                "jang_app.services.studio_realtime_audio.prepare_pitch_shifted_audio",
                return_value=shifted_path,
            ) as prepare:
                playback = prepare_studio_playback_audio((source,))

            prepare.assert_called_once_with(source_path, 12)
            self.assertAlmostEqual(float(np.mean(playback.tracks[0])), 0.3, places=3)

    def test_prepared_clip_keeps_timeline_alignment_and_reverb_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.wav"
            sf.write(path, np.ones((44_100, 2), dtype=np.float32) * 0.25, 44_100)
            effect = StudioEffect(
                "fx-1",
                "reverb",
                reverb=StudioReverbSettings(decay_ms=500),
            )
            source = AudioMixSource(
                "Vocal",
                path,
                timeline_start_ms=100,
                source_start_ms=100,
                source_end_ms=300,
                effects=(effect,),
            )

            prepared = prepare_studio_playback_audio((source,))

            source_audio = np.ones((8_820, 2), dtype=np.float32) * 0.25
            expected = process_mix_source(
                source_audio,
                44_100,
                effects=(effect,),
            )

            self.assertEqual(prepared.tracks[0].shape, expected.shape)
            self.assertTrue(np.allclose(prepared.tracks[0], expected, atol=1e-5))
            self.assertEqual(prepared.track_start_frames, (4_410,))
            self.assertGreater(prepared.track_effect_end_frames[0], 13_230)
            self.assertEqual(prepared.effect_chains, ((),))
            self.assertGreater(prepared.duration_ms, 700)

    def test_split_clips_share_one_decoded_source_without_leading_zero_padding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.wav"
            sf.write(path, np.ones((44_100, 2), dtype=np.float32) * 0.25, 44_100)
            sources = tuple(
                AudioMixSource(
                    f"Clip {index}",
                    path,
                    timeline_start_ms=index * 200,
                    source_start_ms=index * 100,
                    source_end_ms=(index + 1) * 100,
                )
                for index in range(8)
            )

            with patch(
                "jang_app.services.studio_realtime_audio.read_playback_audio",
                wraps=read_playback_audio,
            ) as read_audio:
                prepared = prepare_studio_playback_audio(sources)

            self.assertEqual(read_audio.call_count, 1)
            self.assertEqual(prepared.track_start_frames, tuple(index * 8_820 for index in range(8)))
            self.assertTrue(all(track.shape[0] == 4_410 for track in prepared.tracks))

    def test_level_match_is_baked_into_preview_and_removed_from_live_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "converted.wav"
            reference_path = root / "vocals.wav"
            sf.write(source_path, np.full(44_100, 0.2, dtype=np.float32), 44_100)
            sf.write(reference_path, np.full(44_100, 0.4, dtype=np.float32), 44_100)
            effect = StudioEffect(
                "fx-level",
                "level_match",
                level_match=StudioLevelMatchSettings(100, 100, 12, -60),
            )
            source = AudioMixSource(
                "Converted",
                source_path,
                source_end_ms=1_000,
                effects=(effect,),
                reference_path=reference_path,
            )

            prepared = prepare_studio_playback_audio((source,))

            self.assertAlmostEqual(float(np.mean(prepared.tracks[0])), 0.4, places=2)
            self.assertEqual(prepared.effect_chains, ((),))

    def test_delay_is_baked_and_extends_the_preview_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.wav"
            sf.write(path, np.ones((44_100, 2), dtype=np.float32) * 0.25, 44_100)
            effect = StudioEffect(
                "fx-delay",
                "delay",
                delay=StudioDelaySettings(250, 30, 25, 40),
            )
            source = AudioMixSource(
                "Vocal",
                path,
                source_end_ms=1_000,
                effects=(effect,),
            )

            prepared = prepare_studio_playback_audio((source,))

            self.assertEqual(prepared.effect_chains, ((),))
            self.assertGreater(prepared.duration_ms, 2_000)

    def test_preview_matches_export_volume_and_effect_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.wav"
            frames = np.arange(44_100, dtype=np.float32)
            signal = (0.35 * np.sin(frames * 2 * np.pi * 220 / 44_100))[:, None]
            stereo = np.repeat(signal, 2, axis=1)
            sf.write(path, stereo, 44_100)
            distortion = StudioEffect(
                "fx-distortion",
                "distortion",
                distortion=StudioDistortionSettings(70, 65),
            )
            reverb = StudioEffect(
                "fx-reverb",
                "reverb",
                reverb=StudioReverbSettings(decay_ms=300, dry_wet_percent=45),
            )
            decoded = read_playback_audio(path)
            prepared_tracks = []
            expected_tracks = []
            for effects in ((distortion, reverb), (reverb, distortion)):
                source = AudioMixSource(
                    "Vocal",
                    path,
                    volume=0.4,
                    source_end_ms=1_000,
                    effects=effects,
                )
                prepared = prepare_studio_playback_audio((source,))
                expected = process_mix_source(
                    decoded,
                    44_100,
                    volume=0.4,
                    effects=effects,
                )
                prepared_tracks.append(prepared.tracks[0])
                expected_tracks.append(expected)
                self.assertTrue(np.allclose(prepared.tracks[0], expected, atol=1e-5))
                self.assertEqual(prepared.effect_chains, ((),))

            common = min(track.shape[0] for track in prepared_tracks)
            self.assertGreater(
                float(np.mean(np.abs(
                    prepared_tracks[0][:common] - prepared_tracks[1][:common]
                ))),
                1e-5,
            )


if __name__ == "__main__":
    unittest.main()
