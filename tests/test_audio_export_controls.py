from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.audio_export_controls import AudioExportControls
from jang_app.services.audio_export_settings import (
    AUDIO_FORMAT_FLAC,
    AUDIO_FORMAT_MP3,
    AUDIO_FORMAT_OPUS,
    AUDIO_FORMAT_WAV,
    NORMALIZATION_STREAMING,
    PRESET_CUSTOM,
    PRESET_DISCORD_10MB,
    PRESET_LOSSLESS_FLAC,
    PRESET_MASTER_WAV,
    PRESET_SHARE_MP3,
)


class AudioExportControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_master_preset_is_the_default(self) -> None:
        controls = AudioExportControls()

        settings = controls.settings()

        self.assertEqual(settings.preset_id, PRESET_MASTER_WAV)
        self.assertEqual(settings.format, AUDIO_FORMAT_WAV)
        self.assertEqual(settings.bit_depth, 24)
        controls.close()

    def test_lossless_and_share_presets_apply_complete_profiles(self) -> None:
        controls = AudioExportControls()

        controls.select_preset(PRESET_LOSSLESS_FLAC)
        self.assertEqual(controls.settings().format, AUDIO_FORMAT_FLAC)

        controls.select_preset(PRESET_SHARE_MP3)
        settings = controls.settings()
        self.assertEqual(settings.format, AUDIO_FORMAT_MP3)
        self.assertEqual(settings.normalization, NORMALIZATION_STREAMING)
        self.assertFalse(controls.bit_depth_combo.isEnabled())
        self.assertFalse(controls.dither_check.isEnabled())
        self.assertTrue(controls.bitrate_combo.isEnabled())
        controls.close()

    def test_manual_change_switches_to_custom_without_losing_values(self) -> None:
        controls = AudioExportControls()

        controls.format_combo.setCurrentIndex(controls.format_combo.findData(AUDIO_FORMAT_FLAC))

        settings = controls.settings()
        self.assertEqual(settings.preset_id, PRESET_CUSTOM)
        self.assertEqual(settings.format, AUDIO_FORMAT_FLAC)
        self.assertEqual(settings.output_label, "Custom FLAC")
        controls.close()

    def test_discord_preset_shows_duration_aware_quality_and_size(self) -> None:
        controls = AudioExportControls()
        controls.set_duration_ms(240_000)

        controls.select_preset(PRESET_DISCORD_10MB)
        settings = controls.settings()

        self.assertEqual(settings.preset_id, PRESET_DISCORD_10MB)
        self.assertEqual(settings.format, AUDIO_FORMAT_OPUS)
        self.assertIsNotNone(settings.target_size_bytes)
        self.assertIn("301 kbps", controls.summary_label.text())
        self.assertIn("MB", controls.summary_label.text())
        self.assertTrue(controls.bitrate_combo.isEnabled())
        self.assertFalse(controls.sample_rate_combo.isEnabled())
        controls.close()

    def test_export_button_starts_immediately_and_locks_settings_while_running(self) -> None:
        controls = AudioExportControls()
        requested = QSignalSpy(controls.triggered)

        controls.export_button.click()
        controls.set_running(True)
        controls.set_progress(63)

        self.assertEqual(requested.count(), 1)
        self.assertFalse(controls.export_button.isEnabled())
        self.assertFalse(controls.format_combo.isEnabled())
        self.assertFalse(controls.progress_bar.isHidden())
        self.assertEqual(controls.progress_bar.value(), 63)

        controls.set_running(False)
        self.assertTrue(controls.export_button.isEnabled())
        controls.close()


if __name__ == "__main__":
    unittest.main()
