from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.youtube_video_download import download_youtube_video


class YouTubeVideoDownloadTests(unittest.TestCase):
    def test_downloads_into_managed_directory_and_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "video"
            progress = []
            fake_module = types.SimpleNamespace(YoutubeDL=_FakeYoutubeDL)

            with patch("jang_app.services.youtube_video_download.require_executable", return_value="ffmpeg"):
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


class _FakeYoutubeDL:
    def __init__(self, options: dict) -> None:
        self.options = options

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
