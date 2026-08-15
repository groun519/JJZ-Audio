from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np

from jang_app.services.audio_doubler import apply_doubler, doubler_tail_ms
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.realtime_doubler import RealtimeDoubler
from jang_app.services.realtime_effects import RealtimeEffectChain
from jang_app.services.studio_session import StudioDoublerSettings, StudioEffect


class AudioDoublerTests(unittest.TestCase):
    def test_wide_doubler_creates_separate_left_and_right_voice_arrivals(self) -> None:
        source = np.zeros((400, 2), dtype=np.float32)
        source[-1] = 1.0
        settings = StudioDoublerSettings(18, 0, 100, 100)

        rendered = apply_doubler(source, 8_000, settings)
        left = np.flatnonzero(np.abs(rendered[:, 0]) > 1e-4)
        right = np.flatnonzero(np.abs(rendered[:, 1]) > 1e-4)

        self.assertGreater(rendered.shape[0], source.shape[0])
        self.assertGreater(left.size, 0)
        self.assertGreater(right.size, 0)
        self.assertLess(int(left[0]), int(right[0]))
        self.assertGreater(doubler_tail_ms(settings, 8_000), 18)

    def test_zero_wet_preserves_the_original_shape_and_samples(self) -> None:
        source = np.linspace(-0.5, 0.5, 128, dtype=np.float32)
        settings = StudioDoublerSettings(dry_wet_percent=0)

        rendered = apply_doubler(source, 8_000, settings)

        self.assertEqual(rendered.shape, source.shape)
        np.testing.assert_array_equal(rendered, source)
        self.assertEqual(doubler_tail_ms(settings), 0)

    def test_chunked_processing_matches_one_pass_processing(self) -> None:
        timeline = np.arange(2_000, dtype=np.float32) / 8_000.0
        source = np.sin(2.0 * np.pi * 220.0 * timeline).astype(np.float32)
        settings = StudioDoublerSettings(18, 8, 75, 30)
        whole = RealtimeDoubler(8_000, settings).process(source)
        chunked_processor = RealtimeDoubler(8_000, settings)
        chunked = np.concatenate(
            (
                chunked_processor.process(source[:137]),
                chunked_processor.process(source[137:911]),
                chunked_processor.process(source[911:]),
            ),
            axis=0,
        )

        np.testing.assert_allclose(chunked, whole, atol=1e-6)

    def test_live_settings_update_the_existing_processor(self) -> None:
        effect = StudioEffect("fx-doubler", "doubler")
        chain = RealtimeEffectChain(8_000, (effect,))
        processor = chain._doublers[effect.effect_id]

        chain.update(
            (
                replace(
                    effect,
                    doubler=replace(effect.doubler, pitch_spread_cents=15),
                ),
            )
        )

        self.assertIs(chain._doublers[effect.effect_id], processor)
        self.assertEqual(processor._settings.pitch_spread_cents, 15)

    def test_mix_processing_dispatches_doubler_and_preserves_its_tail(self) -> None:
        source = np.zeros((400, 2), dtype=np.float32)
        source[-1] = 1.0
        effect = StudioEffect(
            "fx-doubler",
            "doubler",
            doubler=StudioDoublerSettings(18, 6, 70, 30),
        )

        rendered = process_mix_source(source, 8_000, effects=(effect,))

        self.assertGreater(rendered.shape[0], source.shape[0])
        self.assertGreater(float(np.max(np.abs(rendered[source.shape[0] :]))), 0.0)


if __name__ == "__main__":
    unittest.main()
