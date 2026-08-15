from __future__ import annotations

import unittest

from jang_app.services.studio_fx_chain_presets import studio_effect_chain


class StudioFxChainPresetTests(unittest.TestCase):
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
