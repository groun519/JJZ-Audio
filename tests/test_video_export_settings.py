from __future__ import annotations

import unittest

from jang_app.services.video_export_settings import (
    ENCODING_SLOW,
    PRESET_COMPACT_720P,
    PRESET_HIGH_QUALITY,
    PRESET_YOUTUBE_1080P,
    VideoExportSettings,
    video_export_preset,
)


class VideoExportSettingsTests(unittest.TestCase):
    def test_youtube_preset_is_the_compatible_1080p_default(self) -> None:
        settings = video_export_preset(PRESET_YOUTUBE_1080P)

        self.assertEqual((settings.width, settings.height), (1920, 1080))
        self.assertEqual(settings.frame_rate, 30)
        self.assertEqual(settings.quality_crf, 18)
        self.assertEqual(settings.audio_bitrate_kbps, 320)
        self.assertEqual(settings.output_label, "YouTube 1080p")

    def test_high_quality_preset_trades_render_time_for_quality(self) -> None:
        settings = video_export_preset(PRESET_HIGH_QUALITY)

        self.assertEqual(settings.quality_crf, 16)
        self.assertEqual(settings.encoding_preset, ENCODING_SLOW)

    def test_compact_preset_reduces_resolution_and_bitrate(self) -> None:
        settings = video_export_preset(PRESET_COMPACT_720P)

        self.assertEqual((settings.width, settings.height), (1280, 720))
        self.assertEqual(settings.quality_crf, 24)
        self.assertEqual(settings.audio_bitrate_kbps, 192)

    def test_invalid_render_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VideoExportSettings(frame_rate=25)


if __name__ == "__main__":
    unittest.main()
