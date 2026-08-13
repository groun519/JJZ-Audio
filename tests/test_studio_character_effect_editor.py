from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_character_effect_editor import StudioCharacterEffectEditor
from jang_app.services.studio_character_fx_presets import character_effect


class StudioCharacterEffectEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preset_and_manual_values_share_one_editor(self) -> None:
        effect = character_effect("radio_filter", "telephone")
        editor = StudioCharacterEffectEditor(effect.kind)
        changed = QSignalSpy(editor.effect_changed)
        editor.set_effect(effect)

        editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("walkie_talkie"))
        self.assertEqual(changed.at(0)[0].radio_filter.low_cut_hz, 420)

        editor.controls["low_cut_hz"].setValue(500)
        editor._flush_changed()
        self.assertEqual(editor.preset_combo.currentData(), "custom")
        self.assertEqual(changed.at(changed.count() - 1)[0].radio_filter.low_cut_hz, 500)
        editor.close()

    def test_each_effect_builds_only_its_relevant_controls(self) -> None:
        expected = {
            "radio_filter": {"low_cut_hz", "high_cut_hz", "mix_percent"},
            "ring_modulator": {"frequency_hz", "mix_percent"},
            "bitcrusher": {"bit_depth", "sample_rate_hz", "mix_percent"},
            "distortion": {"drive_percent", "mix_percent"},
            "level_match": {
                "strength_percent",
                "response_ms",
                "max_correction_db",
                "silence_threshold_db",
            },
        }
        for kind, controls in expected.items():
            with self.subTest(kind=kind):
                editor = StudioCharacterEffectEditor(kind)
                editor.set_effect(character_effect(kind))
                self.assertEqual(set(editor.controls), controls)
                editor.close()


if __name__ == "__main__":
    unittest.main()
