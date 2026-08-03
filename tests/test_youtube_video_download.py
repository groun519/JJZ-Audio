from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.command import CommandResult
from jang_app.services.youtube_video_download import (
    _ensure_preview_compatible,
    download_youtube_video,
)


class YouTubeVideoDownloadTests(unittest.TestCase):
    def test_downloads_into_managed_directory_and_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "video"
            progress = []
            fake_module = types.SimpleNamespace(YoutubeDL=_FakeYoutubeDL)

            with patch("jang_app.services.youtube_video_download.require_executable", return_value="ffmpeg"):
                with patch(
                    "jang_app.services.youtube_video_download._ensure_preview_compatible",
                    side_effect=lambda source, *_args: source,
                ):
                    with patch.dict(sys.modules, {"yt_dlp": fake_module}):
                        result = download_youtube_video(
                            "https://youtube.com/watch?v=abc123",
                            output_dir,
                            progress.append,
                        )

            self.assertEqual(result.title, "Unsafe Title")
            self.assertEqual(result.video_path.parent, output_dir.resolve())
            self.assertEqual(result.video_path.suffix, ".mp4")
            self.assertEqual(result.video_path.read_bytes(), b"downloaded video")
            self.assertEqual(progress[-1], 100)
            self.assertIn("vcodec^=avc1", _FakeYoutubeDL.options_seen["format"])
            self.assertNotIn("+ba", _FakeYoutubeDL.options_seen["format"])

    def test_transcodes_an_incompatible_video_to_h264_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.webm"
            source.write_bytes(b"vp9")
            calls: list[list[str]] = []

            def fake_command(args):
                command = [str(value) for value in args]
                calls.append(command)
                if command[0] == "ffprobe":
                    return CommandResult(args, 0, '{"streams":[{"codec_name":"vp9","pix_fmt":"yuv420p"}]}', "")
                Path(command[-1]).write_bytes(b"h264")
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.youtube_video_download.run_command", side_effect=fake_command):
                converted = _ensure_preview_compatible(source, root, "ffmpeg", "ffprobe")

            self.assertEqual(converted.suffix, ".mp4")
            self.assertEqual(converted.read_bytes(), b"h264")
            self.assertIn("libx264", calls[0])
            self.assertIn("-an", calls[0])


class _FakeYoutubeDL:
    options_seen: dict = {}

    def __init__(self, options: dict) -> None:
        self.options = options
        type(self).options_seen = options

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def extract_info(self, _url: str, *, download: bool):
        self.assert_download = download
        directory = Path(self.options["outtmpl"]).parent
        (directory / "abc123.mp4").write_bytes(b"downloaded video")
        for hook in self.options["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
        for hook in self.options["postprocessor_hooks"]:
            hook({"status": "started"})
            hook({"status": "finished"})
        return {"id": "abc123", "title": "Unsafe Title"}


if __name__ == "__main__":
    unittest.main()
