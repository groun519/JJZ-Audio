from __future__ import annotations

import importlib
import unittest

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language, tr
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


class StudioReverbEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        try:
            self.module = importlib.import_module("jang_app.qt_app.studio_reverb_editor")
        except ModuleNotFoundError:
            self.module = None

    def test_editor_exposes_every_reverb_setting_in_one_page(self) -> None:
        self.assertIsNotNone(self.module)
        editor = self.module.StudioReverbEditor()

        self.assertEqual(
            set(editor.controls),
            set(StudioReverbSettings.__dataclass_fields__),
        )
        self.assertIs(editor.remove_button.parentWidget(), editor)
        editor.close()

    def test_loading_and_editing_emits_a_complete_effect(self) -> None:
        self.assertIsNotNone(self.module)
        editor = self.module.StudioReverbEditor()
        effect = StudioEffect(
            "fx-reverb",
            "reverb",
            reverb=StudioReverbSettings(room_width_m=7.5, dry_wet_percent=35),
        )
        changed = QSignalSpy(editor.effect_changed)
        removed = QSignalSpy(editor.remove_requested)

        editor.set_effect(effect)
        self.assertEqual(editor.controls["room_width_m"].value(), 7.5)
        editor.controls["dry_wet_percent"].setValue(48)
        editor._emit_changed()
        editor.remove_button.click()

        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].effect_id, effect.effect_id)
        self.assertEqual(changed.at(0)[0].reverb.dry_wet_percent, 48)
        self.assertEqual(tuple(removed.at(0)), (effect.effect_id,))
        editor.close()

    def test_value_changes_emit_without_waiting_for_focus_to_leave(self) -> None:
        editor = self.module.StudioReverbEditor()
        editor.set_effect(StudioEffect("fx-reverb", "reverb"))
        changed = QSignalSpy(editor.effect_changed)

        editor.controls["dry_wet_percent"].setValue(67)
        QTest.qWait(45)

        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].reverb.dry_wet_percent, 67)
        editor.close()

    def test_editor_uses_studio_theme_contract_and_translated_help(self) -> None:
        stylesheet = build_stylesheet("dark")

        self.assertIn("QFrame#StudioReverbSection", stylesheet)
        self.assertIn("QSpinBox#StudioReverbControl", stylesheet)
        self.assertIn("QFrame#StudioInspectorTabs", stylesheet)

        set_language(LANGUAGE_KOREAN)
        editor = self.module.StudioReverbEditor()
        self.assertEqual(tr("Remove Effect"), "효과 제거")
        self.assertEqual(editor.remove_button.text(), "효과 제거")
        self.assertIn("가상 공간의 높이", editor.controls["room_height_m"].toolTip())
        editor.close()

    def test_open_editor_refreshes_when_the_app_language_changes(self) -> None:
        set_language(LANGUAGE_ENGLISH)
        editor = self.module.StudioReverbEditor()
        self.assertEqual(editor.remove_button.text(), "Remove Effect")

        set_language(LANGUAGE_KOREAN)
        editor.apply_language()

        self.assertEqual(editor.remove_button.text(), "효과 제거")
        self.assertEqual(editor.field_labels["room_height_m"].text(), "공간 높이")
        editor.close()

    def test_editor_supports_negative_pre_delay_and_precise_distance_help(self) -> None:
        set_language(LANGUAGE_KOREAN)
        editor = self.module.StudioReverbEditor()

        self.assertEqual(editor.controls["pre_delay_ms"].minimum(), -200)
        self.assertIn("초기 반사음만", editor.controls["distance_m"].toolTip())
        self.assertIn("고역", editor.controls["brightness_percent"].toolTip())
        editor.close()


if __name__ == "__main__":
    unittest.main()
