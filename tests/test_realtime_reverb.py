from __future__ import annotations

import unittest

import numpy as np

from jang_app.services.realtime_reverb import RealtimeReverb
from jang_app.services.studio_session import StudioReverbSettings


class RealtimeReverbTests(unittest.TestCase):
    def test_impulse_produces_a_persistent_tail_across_audio_chunks(self) -> None:
        reverb = RealtimeReverb(
            44_100,
            StudioReverbSettings(dry_wet_percent=100, decay_ms=350),
        )
        impulse = np.zeros((128, 2), dtype=np.float32)
        impulse[0] = 1.0

        chunks = [reverb.process(impulse)]
        chunks.extend(
            reverb.process(np.zeros((128, 2), dtype=np.float32))
            for _ in range(18)
        )

        self.assertGreater(float(np.max(np.abs(np.concatenate(chunks)))), 0.01)


if __name__ == "__main__":
    unittest.main()
