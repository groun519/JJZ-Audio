from __future__ import annotations

import unittest

import numpy as np

from jang_app.services.audio_level_match import apply_vocal_level_match
from jang_app.services.studio_session import StudioLevelMatchSettings


class AudioLevelMatchTests(unittest.TestCase):
    def test_processed_vocal_follows_reference_envelope(self) -> None:
        sample_rate = 8_000
        source = np.concatenate(
            (
                np.full(sample_rate, 0.2, dtype=np.float32),
                np.full(sample_rate, 0.8, dtype=np.float32),
            )
        )
        reference = np.full(source.shape, 0.4, dtype=np.float32)
        settings = StudioLevelMatchSettings(100, 100, 12, -60)

        processed = apply_vocal_level_match(source, reference, sample_rate, settings)

        self.assertAlmostEqual(float(np.mean(processed[2_000:6_000])), 0.4, places=2)
        self.assertAlmostEqual(float(np.mean(processed[10_000:14_000])), 0.4, places=2)

    def test_missing_reference_and_silence_are_bypassed(self) -> None:
        source = np.full(8_000, 0.001, dtype=np.float32)
        reference = np.full(8_000, 0.5, dtype=np.float32)
        settings = StudioLevelMatchSettings(100, 100, 12, -50)

        without_reference = apply_vocal_level_match(source, None, 8_000, settings)
        protected_silence = apply_vocal_level_match(source, reference, 8_000, settings)

        np.testing.assert_array_equal(without_reference, source)
        np.testing.assert_allclose(protected_silence, source, atol=1e-7)


if __name__ == "__main__":
    unittest.main()
