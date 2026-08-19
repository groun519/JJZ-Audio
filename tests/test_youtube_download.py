from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.youtube_download import download_youtube_audio


class YouTubeDownloadTests(unittest.TestCase):
    def test_download_uses_bundled_javascript_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "audio"
            fake_module = types.SimpleNamespace(YoutubeDL=_FakeYoutubeDL)
            runtime_options = {"js_runtimes": {"deno": {"path": "deno.exe"}}}

            with patch(
                "jang_app.services.youtube_download.require_executable",
                return_value="ffmpeg",
            ), patch(
                "jang_app.services.youtube_download.youtube_dl_runtime_options",
                return_value=runtime_options,
            ), patch.dict(sys.modules, {"yt_dlp": fake_module}):
                result = download_youtube_audio(
                    "https://youtube.com/watch?v=abc123",
                    output_dir,
                )

            self.assertEqual(result.title, "Downloaded Title")
            self.assertEqual(result.audio_path.parent, output_dir.resolve())
            self.assertEqual(result.audio_path.read_bytes(), b"downloaded audio")
            self.assertEqual(
                _FakeYoutubeDL.options_seen["js_runtimes"],
                runtime_options["js_runtimes"],
            )


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
        (directory / "abc123.m4a").write_bytes(b"downloaded audio")
        return {"id": "abc123", "title": "Downloaded Title"}


if __name__ == "__main__":
    unittest.main()
