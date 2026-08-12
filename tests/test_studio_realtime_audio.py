from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource
from jang_app.services.studio_realtime_audio import prepare_studio_playback_audio
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


class StudioRealtimeAudioTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
