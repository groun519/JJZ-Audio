from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jang_app.services.audio_preview import prepare_preview_audio


class AudioPreviewTests(unittest.TestCase):
    def test_conversion_uses_resolved_ffmpeg_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "voice.m4a"
            source.write_bytes(b"audio")

            def complete(command: list[object]) -> SimpleNamespace:
                Path(command[-1]).write_bytes(b"preview")
                return SimpleNamespace(returncode=0, output="")

            with (
                mock.patch(
                    "jang_app.services.audio_preview.require_executable",
                    return_value="C:/runtime/ffmpeg.exe",
                ),
                mock.patch(
                    "jang_app.services.audio_preview.PREVIEW_WORKSPACE_DIR",
                    Path(temporary) / "previews",
                ),
                mock.patch(
                    "jang_app.services.audio_preview.run_command",
                    side_effect=complete,
                ) as command,
            ):
                preview = prepare_preview_audio(source)

            self.assertTrue(preview.is_file())
            self.assertEqual(command.call_args.args[0][0], "C:/runtime/ffmpeg.exe")


if __name__ == "__main__":
    unittest.main()
