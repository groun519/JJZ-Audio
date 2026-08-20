from __future__ import annotations

import unittest

import numpy as np

from jang_app.services.audio_hard_tune import (
    HardTuneProcessor,
    apply_hard_tune,
    quantized_pitch_midi,
)
from jang_app.services.pitch_profile import estimate_pitch_midi
from jang_app.services.studio_session import StudioHardTuneSettings


class AudioHardTuneTests(unittest.TestCase):
    def test_pitch_is_quantized_to_selected_scale(self) -> None:
        self.assertEqual(quantized_pitch_midi(61.2, 0, "chromatic"), 61.0)
        self.assertEqual(quantized_pitch_midi(61.2, 0, "major"), 62.0)
        self.assertEqual(quantized_pitch_midi(63.1, 0, "minor"), 63.0)

    def test_hard_tune_moves_an_offset_tone_toward_nearest_note(self) -> None:
        sample_rate = 44_100
        source_midi = 57.35
        frequency = 440.0 * 2.0 ** ((source_midi - 69.0) / 12.0)
        time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
        source = (0.35 * np.sin(2.0 * np.pi * frequency * time)).astype(np.float32)

        processed = apply_hard_tune(
            source,
            sample_rate,
            StudioHardTuneSettings(
                strength_percent=100,
                response_ms=10,
                vibrato_preserve_percent=0,
            ),
        )

        detected = estimate_pitch_midi(processed[-4_096:], sample_rate)
        self.assertIsNotNone(detected)
        self.assertAlmostEqual(float(detected), 57.0, delta=0.2)
        self.assertEqual(processed.shape, source.shape)
        self.assertTrue(np.isfinite(processed).all())

    def test_streaming_and_one_pass_processing_match(self) -> None:
        sample_rate = 16_000
        time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
        source = np.stack(
            (
                0.3 * np.sin(2.0 * np.pi * 227.0 * time),
                0.3 * np.sin(2.0 * np.pi * 227.0 * time),
            ),
            axis=1,
        ).astype(np.float32)
        settings = StudioHardTuneSettings(response_ms=30)

        rendered = apply_hard_tune(source, sample_rate, settings)
        processor = HardTuneProcessor(sample_rate, settings)
        streamed = np.concatenate(
            tuple(
                processor.process(source[start : start + 1_024])
                for start in range(0, len(source), 1_024)
            )
        )

        np.testing.assert_allclose(streamed, rendered, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
