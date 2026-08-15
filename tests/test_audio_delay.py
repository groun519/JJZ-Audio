from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np

from jang_app.services.audio_delay import apply_delay, delay_tail_ms
from jang_app.services.realtime_effects import RealtimeEffectChain
from jang_app.services.studio_session import (
    StudioDelaySettings,
    StudioEffect,
)


class AudioDelayTests(unittest.TestCase):
    def test_first_echo_lands_on_the_configured_interval(self) -> None:
        source = np.zeros((100, 1), dtype=np.float32)
        source[0, 0] = 1.0
        settings = StudioDelaySettings(
            delay_ms=100,
            feedback_percent=0,
            dry_wet_percent=100,
            stereo_width_percent=0,
        )

        rendered = apply_delay(source, 8_000, settings)

        self.assertEqual(rendered.shape, (900, 2))
        self.assertAlmostEqual(float(rendered[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(rendered[800, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(rendered[800, 1]), 1.0, places=6)

    def test_stereo_width_separates_the_right_repeat(self) -> None:
        source = np.zeros((100, 1), dtype=np.float32)
        source[0, 0] = 1.0
        settings = StudioDelaySettings(100, 0, 100, 100)

        rendered = apply_delay(source, 8_000, settings)

        self.assertAlmostEqual(float(rendered[800, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(rendered[800, 1]), 0.0, places=6)
        self.assertAlmostEqual(float(rendered[992, 1]), 1.0, places=6)

    def test_zero_wet_preserves_the_source_shape_and_samples(self) -> None:
        source = np.linspace(-0.5, 0.5, 32, dtype=np.float32)[:, None]

        rendered = apply_delay(
            source,
            8_000,
            StudioDelaySettings(dry_wet_percent=0),
        )

        self.assertEqual(rendered.shape, source.shape)
        np.testing.assert_allclose(rendered, source, atol=1e-7)
        self.assertEqual(delay_tail_ms(StudioDelaySettings(dry_wet_percent=0)), 0)

    def test_live_delay_settings_update_the_existing_processor(self) -> None:
        effect = StudioEffect("fx-delay", "delay")
        chain = RealtimeEffectChain(44_100, (effect,))
        processor = chain._delays[effect.effect_id]

        chain.update(
            (
                replace(
                    effect,
                    delay=replace(effect.delay, delay_ms=480, feedback_percent=50),
                ),
            )
        )

        self.assertIs(chain._delays[effect.effect_id], processor)
        self.assertEqual(processor._settings.delay_ms, 480)


if __name__ == "__main__":
    unittest.main()
