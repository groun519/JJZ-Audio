from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource
from jang_app.services.studio_realtime_audio import prepare_studio_playback_audio
from jang_app.services.studio_session import (
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

            self.assertEqual(prepared.tracks[0].shape[0], 13_230)
            self.assertTrue(np.allclose(prepared.tracks[0][:4_410], 0.0))
            self.assertEqual(prepared.effect_chains, ((effect,),))
            self.assertGreater(prepared.duration_ms, 1_000)

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


if __name__ == "__main__":
    unittest.main()
