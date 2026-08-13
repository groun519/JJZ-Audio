from __future__ import annotations

import unittest

from jang_app.services.audio_export_settings import (
    AUDIO_FORMAT_FLAC,
    AUDIO_FORMAT_MP3,
    AUDIO_FORMAT_OPUS,
    DISCORD_TARGET_BYTES,
    PRESET_CUSTOM,
    PRESET_DISCORD_10MB,
    NORMALIZATION_STREAMING,
    PRESET_LOSSLESS_FLAC,
    PRESET_MASTER_WAV,
    PRESET_SHARE_MP3,
    AudioExportSettings,
    audio_export_preset,
    discord_opus_bitrate_kbps,
    estimated_opus_size_bytes,
)


class AudioExportSettingsTests(unittest.TestCase):
    def test_presets_define_user_facing_delivery_formats(self) -> None:
        master = audio_export_preset(PRESET_MASTER_WAV)
        lossless = audio_export_preset(PRESET_LOSSLESS_FLAC)
        share = audio_export_preset(PRESET_SHARE_MP3)

        self.assertEqual((master.extension, master.bit_depth), (".wav", 24))
        self.assertEqual((lossless.format, lossless.output_label), (AUDIO_FORMAT_FLAC, "Lossless FLAC"))
        self.assertEqual(share.format, AUDIO_FORMAT_MP3)
        self.assertEqual(share.normalization, NORMALIZATION_STREAMING)
        self.assertEqual(share.mp3_bitrate_kbps, 320)

    def test_discord_preset_targets_ogg_opus_below_ten_megabytes(self) -> None:
        settings = audio_export_preset(PRESET_DISCORD_10MB)

        self.assertEqual(settings.format, AUDIO_FORMAT_OPUS)
        self.assertEqual(settings.extension, ".ogg")
        self.assertEqual(settings.target_size_bytes, DISCORD_TARGET_BYTES)
        self.assertIsNone(settings.opus_bitrate_kbps)
        self.assertEqual(settings.output_label, "Discord 10MB")

    def test_discord_bitrate_uses_the_highest_safe_value_for_duration(self) -> None:
        bitrate = discord_opus_bitrate_kbps(240)
        estimated = estimated_opus_size_bytes(240, bitrate)

        self.assertEqual(bitrate, 301)
        self.assertLess(estimated, DISCORD_TARGET_BYTES)

    def test_discord_bitrate_rejects_music_too_long_for_the_size_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "too long"):
            discord_opus_bitrate_kbps(1_800)

    def test_invalid_format_specific_bit_depth_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "FLAC"):
            AudioExportSettings(format=AUDIO_FORMAT_FLAC, bit_depth=32)

    def test_custom_output_name_identifies_its_format(self) -> None:
        settings = AudioExportSettings(preset_id=PRESET_CUSTOM, format=AUDIO_FORMAT_FLAC)

        self.assertEqual(settings.output_label, "Custom FLAC")


if __name__ == "__main__":
    unittest.main()
