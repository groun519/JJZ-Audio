from __future__ import annotations

import unittest

from jang_app.services.video_export_settings import (
    ENCODING_SLOW,
    PRESET_COMPACT_720P,
    PRESET_DISCORD_10MB,
    PRESET_HIGH_QUALITY,
    PRESET_YOUTUBE_1080P,
    VIDEO_TARGET_10MB_BYTES,
    VideoExportSettings,
    video_encoding_plan,
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

    def test_10mb_preset_uses_a_bitrate_budget_without_guessing_resolution(self) -> None:
        settings = video_export_preset(PRESET_DISCORD_10MB)

        short_plan = video_encoding_plan(settings, 60)
        song_plan = video_encoding_plan(settings, 180)

        self.assertEqual(settings.target_size_bytes, VIDEO_TARGET_10MB_BYTES)
        self.assertEqual((settings.width, settings.height), (1920, 1080))
        self.assertEqual(
            (short_plan.settings.width, short_plan.settings.height),
            (1920, 1080),
        )
        self.assertEqual(
            (song_plan.settings.width, song_plan.settings.height),
            (1920, 1080),
        )
        self.assertIsNotNone(song_plan.video_bitrate_kbps)
        self.assertLess(song_plan.video_bitrate_kbps, short_plan.video_bitrate_kbps)

    def test_10mb_plan_rejects_a_video_too_long_for_usable_quality(self) -> None:
        with self.assertRaises(ValueError):
            video_encoding_plan(video_export_preset(PRESET_DISCORD_10MB), 1_200)

    def test_invalid_render_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VideoExportSettings(frame_rate=25)


if __name__ == "__main__":
    unittest.main()
