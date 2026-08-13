from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_export_settings import (
    AUDIO_FORMAT_MP3,
    AUDIO_FORMAT_OPUS,
    NORMALIZATION_STREAMING,
    AudioExportSettings,
)
from jang_app.services.final_audio_export import (
    _encoding_command,
    export_final_audio_mix,
)
from jang_app.services.command import CommandResult


class FinalAudioExportTests(unittest.TestCase):
    def test_master_wav_is_24_bit_and_protects_overloads_without_boosting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            output = root / "master.wav"
            sf.write(source, np.array([0.8, 0.2], dtype=np.float32), 8_000, subtype="FLOAT")

            export_final_audio_mix(
                (AudioMixSource("One", source), AudioMixSource("Two", source)),
                output,
                AudioExportSettings(),
            )

            rendered, sample_rate = sf.read(output, dtype="float32")
            self.assertEqual(sf.info(output).subtype, "PCM_24")
            self.assertEqual(sample_rate, 8_000)
            self.assertAlmostEqual(float(rendered[0]), 10 ** (-1 / 20), places=4)
            self.assertAlmostEqual(float(rendered[1]), (0.4 / 1.6) * 10 ** (-1 / 20), places=4)

    def test_mp3_command_uses_streaming_loudness_and_high_quality_resampling(self) -> None:
        settings = AudioExportSettings(
            format=AUDIO_FORMAT_MP3,
            normalization=NORMALIZATION_STREAMING,
            dither=False,
        )
        command = _encoding_command(
            "ffmpeg",
            Path("master.wav"),
            Path("share.mp3"),
            96_000,
            48_000,
            settings,
            {
                "input_i": "-18.0",
                "input_tp": "-2.0",
                "input_lra": "4.0",
                "input_thresh": "-28.0",
                "target_offset": "0.1",
            },
        )

        filters = command[command.index("-af") + 1]
        self.assertIn("loudnorm=I=-14:TP=-1", filters)
        self.assertIn("aresample=48000", filters)
        self.assertIn("libmp3lame", command)
        self.assertIn("320k", command)

    def test_size_targeted_opus_command_uses_duration_based_constrained_vbr(self) -> None:
        settings = AudioExportSettings(
            format=AUDIO_FORMAT_OPUS,
            sample_rate=48_000,
            dither=False,
            opus_bitrate_kbps=None,
            target_size_bytes=9_500_000,
        )

        command = _encoding_command(
            "ffmpeg",
            Path("master.wav"),
            Path("discord.ogg"),
            44_100,
            48_000,
            settings,
            duration_seconds=240,
        )

        self.assertIn("libopus", command)
        self.assertEqual(command[command.index("-b:a") + 1], "301k")
        self.assertEqual(command[command.index("-vbr") + 1], "constrained")
        self.assertIn("aresample=48000", command[command.index("-af") + 1])

    def test_oversized_opus_is_reencoded_at_a_lower_bitrate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            output = root / "discord.ogg"
            sf.write(source, np.zeros(48_000, dtype=np.float32), 48_000)
            settings = AudioExportSettings(
                format=AUDIO_FORMAT_OPUS,
                sample_rate=48_000,
                dither=False,
                opus_bitrate_kbps=None,
                target_size_bytes=1_000_000,
            )
            bitrates: list[int] = []

            def fake_run(command, **_options):
                args = list(command)
                bitrates.append(int(args[args.index("-b:a") + 1].removesuffix("k")))
                encoded = Path(args[-1])
                encoded.write_bytes(b"x" * (1_050_000 if len(bitrates) == 1 else 900_000))
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.final_audio_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.final_audio_export.run_command", side_effect=fake_run):
                    export_final_audio_mix(
                        (AudioMixSource("Source", source),),
                        output,
                        settings,
                    )

            self.assertEqual(len(bitrates), 2)
            self.assertLess(bitrates[1], bitrates[0])
            self.assertLessEqual(output.stat().st_size, settings.target_size_bytes)


if __name__ == "__main__":
    unittest.main()
