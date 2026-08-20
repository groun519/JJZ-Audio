from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_hard_tune_editor import StudioHardTuneEditor
from jang_app.qt_app.widgets import ScrollSafeComboBox
from jang_app.services.studio_hard_tune_presets import hard_tune_preset_settings
from jang_app.services.studio_session import StudioEffect, StudioHardTuneSettings


class StudioHardTuneEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_exposes_every_setting_and_choice_field(self) -> None:
        editor = StudioHardTuneEditor()

        self.assertEqual(
            set(editor.controls),
            set(StudioHardTuneSettings.__dataclass_fields__),
        )
        self.assertIsInstance(editor.controls["key_note"], ScrollSafeComboBox)
        self.assertIsInstance(editor.controls["scale"], ScrollSafeComboBox)
        self.assertEqual(editor.controls["key_note"].count(), 12)
        self.assertEqual(editor.controls["scale"].count(), 3)
        editor.close()

    def test_loading_and_editing_preserves_choice_values(self) -> None:
        editor = StudioHardTuneEditor()
        effect = StudioEffect(
            "fx-hard-tune",
            "hard_tune",
            hard_tune=StudioHardTuneSettings(key_note=9, scale="minor"),
        )
        changed = QSignalSpy(editor.effect_changed)

        editor.set_effect(effect)
        editor.controls["strength_percent"].setValue(100)
        editor._emit_changed()

        self.assertEqual(changed.count(), 1)
        updated = changed.at(0)[0]
        self.assertEqual(updated.hard_tune.key_note, 9)
        self.assertEqual(updated.hard_tune.scale, "minor")
        self.assertEqual(updated.hard_tune.strength_percent, 100)
        editor.close()

    def test_synth_preset_applies_the_complete_setting_group(self) -> None:
        editor = StudioHardTuneEditor()
        editor.set_effect(StudioEffect("fx-hard-tune", "hard_tune"))
        changed = QSignalSpy(editor.effect_changed)

        editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("synth"))

        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].hard_tune, hard_tune_preset_settings("synth"))
        editor.close()


if __name__ == "__main__":
    unittest.main()
