from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jang_app.services.audio_metadata import clear_audio_metadata_cache, read_audio_metadata


class AudioMetadataTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_audio_metadata_cache()

    def test_unchanged_file_metadata_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "voice.wav"
            source.write_bytes(b"audio")
            info = SimpleNamespace(duration=1.25, samplerate=44_100, channels=1)

            with mock.patch("jang_app.services.audio_metadata.sf.info", return_value=info) as probe:
                first = read_audio_metadata(source)
                second = read_audio_metadata(source)

            self.assertEqual(first, second)
            self.assertEqual(first.duration_ms, 1_250)
            probe.assert_called_once()

    def test_mutagen_reads_m4a_without_starting_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "voice.m4a"
            source.write_bytes(b"audio")
            audio = SimpleNamespace(
                info=SimpleNamespace(length=2.5, sample_rate=44_100, channels=2)
            )

            with (
                mock.patch(
                    "jang_app.services.audio_metadata.sf.info",
                    side_effect=RuntimeError("unsupported"),
                ),
                mock.patch(
                    "jang_app.services.audio_metadata.open_mutagen_file",
                    return_value=audio,
                ) as mutagen_probe,
                mock.patch("jang_app.services.audio_metadata.run_command") as ffprobe,
            ):
                first = read_audio_metadata(source)
                second = read_audio_metadata(source)

            self.assertEqual(first, second)
            self.assertEqual(first.duration_ms, 2_500)
            self.assertEqual(first.sample_rate, 44_100)
            self.assertEqual(first.channels, 2)
            mutagen_probe.assert_called_once_with(source.resolve())
            ffprobe.assert_not_called()

    def test_ffprobe_fallback_is_not_repeated_for_unchanged_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "voice.m4a"
            source.write_bytes(b"audio")
            completed = SimpleNamespace(
                returncode=0,
                stdout="sample_rate=44100\nchannels=2\nduration=2.5\n",
            )

            with (
                mock.patch(
                    "jang_app.services.audio_metadata.sf.info",
                    side_effect=RuntimeError("unsupported"),
                ),
                mock.patch(
                    "jang_app.services.audio_metadata.open_mutagen_file",
                    side_effect=RuntimeError("unsupported"),
                ),
                mock.patch(
                    "jang_app.services.audio_metadata.require_executable",
                    return_value="C:/runtime/ffprobe.exe",
                ),
                mock.patch(
                    "jang_app.services.audio_metadata.run_command",
                    return_value=completed,
                ) as probe,
            ):
                first = read_audio_metadata(source)
                second = read_audio_metadata(source)

            self.assertEqual(first, second)
            self.assertEqual(first.duration_ms, 2_500)
            probe.assert_called_once()
            self.assertEqual(probe.call_args.args[0][0], "C:/runtime/ffprobe.exe")


if __name__ == "__main__":
    unittest.main()
