from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.video_export_controls import VideoExportControls
from jang_app.services.video_export_settings import (
    PRESET_COMPACT_720P,
    PRESET_CUSTOM,
    PRESET_DISCORD_10MB,
    PRESET_HIGH_QUALITY,
)


class VideoExportControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preset_populates_all_render_settings(self) -> None:
        controls = VideoExportControls()

        controls.select_preset(PRESET_COMPACT_720P)
        settings = controls.settings()

        self.assertEqual(settings.preset_id, PRESET_COMPACT_720P)
        self.assertEqual((settings.width, settings.height), (1280, 720))
        self.assertIn("1280 x 720", controls.summary_label.text())
        controls.close()

    def test_manual_change_switches_to_custom(self) -> None:
        controls = VideoExportControls()
        controls.select_preset(PRESET_HIGH_QUALITY)

        controls.frame_rate_combo.setCurrentIndex(
            controls.frame_rate_combo.findData(60)
        )

        self.assertEqual(controls.settings().preset_id, PRESET_CUSTOM)
        self.assertEqual(controls.settings().frame_rate, 60)
        controls.close()

    def test_10mb_preset_exposes_automatic_size_target(self) -> None:
        controls = VideoExportControls()

        controls.select_preset(PRESET_DISCORD_10MB)
        settings = controls.settings()

        self.assertEqual(settings.preset_id, PRESET_DISCORD_10MB)
        self.assertIsNotNone(settings.target_size_bytes)
        self.assertIn("10MB", controls.summary_label.text().replace(" ", ""))
        self.assertFalse(controls.resolution_combo.isEnabled())
        self.assertFalse(controls.audio_bitrate_combo.isEnabled())
        controls.close()

    def test_running_state_locks_settings_and_action(self) -> None:
        controls = VideoExportControls()
        controls.set_action_enabled(True)

        controls.set_running(True)

        self.assertFalse(controls.button.isEnabled())
        self.assertFalse(controls.resolution_combo.isEnabled())
        controls.set_running(False)
        self.assertTrue(controls.button.isEnabled())
        controls.close()


if __name__ == "__main__":
    unittest.main()
