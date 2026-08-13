from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.rvc_inference_controls import RvcInferenceControls
from jang_app.services.rvc_inference_settings import (
    PRESET_CUSTOM,
    PRESET_DETAIL,
    RvcInferenceSettings,
)


class RvcInferenceControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selecting_preset_updates_every_runtime_value(self) -> None:
        controls = RvcInferenceControls()

        controls.preset_buttons[PRESET_DETAIL].click()

        self.assertEqual(
            controls.settings(),
            RvcInferenceSettings(index_rate=0.55, protect=0.20),
        )

    def test_manual_change_selects_custom(self) -> None:
        controls = RvcInferenceControls()

        controls.index_rate_control.setValue(0.62)

        self.assertFalse(any(button.isChecked() for button in controls.preset_buttons.values()))
        self.assertTrue(controls.custom_badge.isVisibleTo(controls))
        self.assertEqual(controls.settings().index_rate, 0.62)

    def test_detailed_values_are_collapsed_until_requested(self) -> None:
        controls = RvcInferenceControls()

        self.assertFalse(controls.details_panel.isVisibleTo(controls))
        self.assertEqual(controls.details_button.icon_name(), "chevron_down")
        controls.details_button.click()

        self.assertTrue(controls.details_panel.isVisibleTo(controls))
        self.assertEqual(controls.details_button.icon_name(), "chevron_up")


if __name__ == "__main__":
    unittest.main()
