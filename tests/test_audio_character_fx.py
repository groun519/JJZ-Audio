from __future__ import annotations

import unittest

import numpy as np

from jang_app.services.audio_character_fx import (
    apply_character_effect,
    create_character_effect_processor,
)
from jang_app.services.studio_character_fx_presets import character_effect


class AudioCharacterFxTests(unittest.TestCase):
    def test_each_character_effect_changes_audio_without_changing_shape(self) -> None:
        sample_rate = 16_000
        time = np.arange(sample_rate, dtype=np.float32) / sample_rate
        source = np.stack(
            (np.sin(2 * np.pi * 220 * time), np.sin(2 * np.pi * 440 * time)),
            axis=1,
        ).astype(np.float32)
        effects = (
            character_effect("radio_filter", "telephone"),
            character_effect("ring_modulator", "robot"),
            character_effect("bitcrusher", "broken_8bit"),
            character_effect("distortion", "overdrive"),
        )

        for effect in effects:
            with self.subTest(effect=effect.kind):
                processed = apply_character_effect(source, sample_rate, effect)
                self.assertEqual(processed.shape, source.shape)
                self.assertEqual(processed.dtype, np.float32)
                self.assertTrue(np.isfinite(processed).all())
                self.assertGreater(float(np.max(np.abs(processed - source))), 0.01)

    def test_live_chunk_processing_matches_one_pass_rendering(self) -> None:
        sample_rate = 16_000
        source = np.linspace(-0.8, 0.8, 4_003, dtype=np.float32)[:, None]
        effects = (
            character_effect("radio_filter", "walkie_talkie"),
            character_effect("ring_modulator", "subtle_metal"),
            character_effect("bitcrusher", "retro_10bit"),
            character_effect("distortion", "grit"),
        )

        for effect in effects:
            with self.subTest(effect=effect.kind):
                rendered = apply_character_effect(source, sample_rate, effect)
                processor = create_character_effect_processor(sample_rate, effect)
                chunked = np.concatenate(
                    tuple(
                        processor.process(source[start : start + 257])
                        for start in range(0, len(source), 257)
                    )
                )
                np.testing.assert_allclose(chunked, rendered, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
