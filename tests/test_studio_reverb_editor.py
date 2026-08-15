from __future__ import annotations

import importlib
import unittest

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import DangerIconButton, ToggleSwitchButton
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language, tr
from jang_app.services.studio_reverb_presets import (
    CUSTOM_REVERB_PRESET,
    STUDIO_REVERB_PRESETS,
    matching_reverb_preset,
    reverb_preset_settings,
)
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
        self.assertEqual(set(editor.field_info_buttons), set(editor.controls))
        self.assertTrue(
            all(button.text() == "i" for button in editor.field_info_buttons.values())
        )
        self.assertIsInstance(editor.enabled_button, ToggleSwitchButton)
        self.assertIsInstance(editor.remove_button, DangerIconButton)
        self.assertEqual(editor.remove_button.text(), "")
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
        QTest.qWait(80)

        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].reverb.dry_wet_percent, 67)
        editor.close()

    def test_preset_selection_applies_all_values_as_one_effect_change(self) -> None:
        editor = self.module.StudioReverbEditor()
        editor.set_effect(StudioEffect("fx-reverb", "reverb"))
        changed = QSignalSpy(editor.effect_changed)

        editor.preset_combo.setCurrentIndex(
            editor.preset_combo.findData("vocal_plate")
        )

        expected = reverb_preset_settings("vocal_plate")
        self.assertIsNotNone(expected)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].reverb, expected)
        self.assertEqual(editor.controls["decay_ms"].value(), expected.decay_ms)
        editor.close()

    def test_manual_edit_switches_preset_to_custom(self) -> None:
        editor = self.module.StudioReverbEditor()
        settings = reverb_preset_settings("warm_room")
        self.assertIsNotNone(settings)
        editor.set_effect(StudioEffect("fx-reverb", "reverb", reverb=settings))

        self.assertEqual(editor.preset_combo.currentData(), "warm_room")
        editor.controls["dry_wet_percent"].setValue(31)

        self.assertEqual(editor.preset_combo.currentData(), CUSTOM_REVERB_PRESET)
        self.assertEqual(editor.preset_combo.currentText(), tr("Custom"))
        editor.close()

    def test_preset_names_are_single_words_and_bloom_uses_reference_values(self) -> None:
        set_language(LANGUAGE_ENGLISH)
        editor = self.module.StudioReverbEditor()
        names = [
            editor.preset_combo.itemText(index)
            for index in range(editor.preset_combo.count())
        ]
        bloom = reverb_preset_settings("bloom")

        self.assertEqual(
            names,
            [
                "Karaoke",
                "Natural",
                "Warm",
                "Plate",
                "Hall",
                "Dream",
                "Bloom",
                "Custom",
            ],
        )
        self.assertIsNotNone(bloom)
        self.assertEqual(
            (
                bloom.room_height_m,
                bloom.room_length_m,
                bloom.room_width_m,
                bloom.distance_m,
                bloom.pre_delay_ms,
                bloom.decay_ms,
                bloom.dry_wet_percent,
            ),
            (10.0, 16.0, 20.0, 10.0, 50, 950, 30),
        )
        editor.close()

    def test_existing_settings_restore_matching_preset_or_custom(self) -> None:
        editor = self.module.StudioReverbEditor()
        natural = StudioReverbSettings()
        custom = StudioReverbSettings(decay_ms=1_337)

        editor.set_effect(StudioEffect("fx-natural", "reverb", reverb=natural))
        self.assertEqual(matching_reverb_preset(natural), "natural_vocal")
        self.assertEqual(editor.preset_combo.currentData(), "natural_vocal")

        editor.set_effect(StudioEffect("fx-custom", "reverb", reverb=custom))
        self.assertEqual(editor.preset_combo.currentData(), CUSTOM_REVERB_PRESET)
        editor.close()

    def test_every_preset_survives_editor_roundtrip(self) -> None:
        editor = self.module.StudioReverbEditor()

        for preset in STUDIO_REVERB_PRESETS:
            editor.set_effect(
                StudioEffect(
                    f"fx-{preset.key}",
                    "reverb",
                    reverb=StudioReverbSettings(decay_ms=1_337),
                )
            )
            changed = QSignalSpy(editor.effect_changed)

            editor.preset_combo.setCurrentIndex(
                editor.preset_combo.findData(preset.key)
            )

            self.assertEqual(changed.count(), 1, preset.key)
            updated = changed.at(0)[0]
            self.assertEqual(updated.reverb, preset.settings, preset.key)
            editor.set_effect(updated)
            self.assertEqual(editor.preset_combo.currentData(), preset.key)

        self.assertEqual(editor.controls["distance_m"].decimals(), 2)
        self.assertEqual(editor.controls["distance_m"].singleStep(), 0.05)
        editor.close()

    def test_effect_toggle_bypasses_without_losing_current_settings(self) -> None:
        set_language(LANGUAGE_ENGLISH)
        editor = self.module.StudioReverbEditor()
        effect = StudioEffect(
            "fx-reverb",
            "reverb",
            enabled=False,
            reverb=StudioReverbSettings(dry_wet_percent=35),
        )
        changed = QSignalSpy(editor.effect_changed)
        editor.set_effect(effect)

        self.assertFalse(editor.enabled_button.isChecked())
        self.assertEqual(editor.enabled_button.text(), "")
        editor.controls["dry_wet_percent"].setValue(47)
        editor.enabled_button.click()

        self.assertEqual(changed.count(), 1)
        updated = changed.at(0)[0]
        self.assertTrue(updated.enabled)
        self.assertEqual(updated.reverb.dry_wet_percent, 47)
        self.assertTrue(editor.controls["dry_wet_percent"].isEnabled())
        self.assertEqual(editor.enabled_button.text(), "")

        editor.controls["decay_ms"].setValue(1_250)
        editor._emit_changed()
        self.assertTrue(changed.at(1)[0].enabled)
        editor.close()

    def test_editor_uses_studio_theme_contract_and_translated_help(self) -> None:
        stylesheet = build_stylesheet("dark")

        self.assertIn("QFrame#StudioReverbSection", stylesheet)
        self.assertIn("QSpinBox#StudioReverbControl", stylesheet)
        self.assertIn("QFrame#StudioReverbActionBar", stylesheet)
        self.assertIn("QPushButton#ToggleSwitchButton", stylesheet)
        self.assertIn("QFrame#StudioInspectorTabs", stylesheet)

        set_language(LANGUAGE_KOREAN)
        editor = self.module.StudioReverbEditor()
        self.assertEqual(tr("Remove Effect"), "효과 제거")
        self.assertEqual(editor.remove_button.toolTip(), "효과 제거")
        body, recommendation = self.module._FIELD_HELP["room_height_m"]
        self.assertIn(tr(body), editor.controls["room_height_m"].toolTip())
        self.assertIn(tr(body), editor.field_info_buttons["room_height_m"].toolTip())
        self.assertIn(
            tr(recommendation),
            editor.field_info_buttons["room_height_m"].toolTip(),
        )
        self.assertIn(tr(self.module._PRESET_HELP[0]), editor.preset_info.toolTip())
        editor.close()

    def test_open_editor_refreshes_when_the_app_language_changes(self) -> None:
        set_language(LANGUAGE_ENGLISH)
        editor = self.module.StudioReverbEditor()
        self.assertEqual(editor.remove_button.toolTip(), "Remove Effect")

        set_language(LANGUAGE_KOREAN)
        editor.apply_language()

        self.assertEqual(editor.remove_button.toolTip(), "효과 제거")
        self.assertEqual(editor.field_labels["room_height_m"].text(), "공간 높이")
        editor.close()

    def test_editor_supports_negative_pre_delay_and_precise_distance_help(self) -> None:
        set_language(LANGUAGE_KOREAN)
        editor = self.module.StudioReverbEditor()

        self.assertEqual(editor.controls["pre_delay_ms"].minimum(), -200)
        distance_help = self.module._FIELD_HELP["distance_m"]
        brightness_help = self.module._FIELD_HELP["brightness_percent"]
        self.assertIn(
            tr(distance_help[0]),
            editor.field_info_buttons["distance_m"].toolTip(),
        )
        self.assertIn(
            tr(distance_help[1]),
            editor.field_info_buttons["distance_m"].toolTip(),
        )
        self.assertIn(
            tr(brightness_help[0]),
            editor.field_info_buttons["brightness_percent"].toolTip(),
        )
        editor.close()

    def test_beginner_help_is_translated_and_layout_stays_compact(self) -> None:
        set_language(LANGUAGE_KOREAN)
        editor = self.module.StudioReverbEditor()
        editor.setStyleSheet(build_stylesheet("dark"))
        editor.ensurePolished()

        help_texts = [text for pair in self.module._FIELD_HELP.values() for text in pair]
        help_texts.extend(self.module._PRESET_HELP)
        for text in help_texts:
            self.assertNotEqual(tr(text), text)
        self.assertLessEqual(editor.minimumSizeHint().width(), 352)
        editor.close()


if __name__ == "__main__":
    unittest.main()
