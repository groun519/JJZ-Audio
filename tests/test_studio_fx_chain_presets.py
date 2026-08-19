from __future__ import annotations

import unittest

from jang_app.services.studio_fx_chain_presets import studio_effect_chain


class StudioFxChainPresetTests(unittest.TestCase):
    def test_lush_chain_combines_bloom_reverb_and_balanced_level_match(self) -> None:
        effects = studio_effect_chain("lush")

        self.assertEqual(
            tuple(effect.kind for effect in effects),
            ("reverb", "level_match"),
        )
        self.assertEqual(len({effect.effect_id for effect in effects}), 2)
        self.assertEqual(effects[0].reverb.room_length_m, 16.0)
        self.assertEqual(effects[0].reverb.decay_ms, 950)
        self.assertEqual(effects[1].level_match.strength_percent, 75)
        self.assertEqual(effects[1].level_match.response_ms, 180)

    def test_karaoke_chain_uses_editable_time_effects(self) -> None:
        effects = studio_effect_chain("karaoke")

        self.assertEqual(tuple(effect.kind for effect in effects), ("delay", "reverb"))
        self.assertEqual(len({effect.effect_id for effect in effects}), 2)
        self.assertEqual(effects[0].delay.stereo_width_percent, 55)
        self.assertEqual(effects[1].reverb.pre_delay_ms, 22)

    def test_existing_character_chain_is_preserved(self) -> None:
        effects = studio_effect_chain("walkie_talkie")

        self.assertEqual(
            tuple(effect.kind for effect in effects),
            ("radio_filter", "bitcrusher", "distortion"),
        )


if __name__ == "__main__":
    unittest.main()
