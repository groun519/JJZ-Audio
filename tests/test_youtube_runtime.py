from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.youtube_runtime import (
    YouTubeRuntimeError,
    resolve_deno_executable,
    youtube_dl_runtime_options,
)


class YouTubeRuntimeTests(unittest.TestCase):
    def test_prefers_bundled_deno_and_passes_its_path_to_ytdlp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            deno = Path(temporary) / "deno.exe"
            deno.write_bytes(b"deno")

            with patch(
                "jang_app.services.youtube_runtime._bundled_deno_candidates",
                return_value=(deno,),
            ):
                options = youtube_dl_runtime_options()

            self.assertEqual(
                options,
                {"js_runtimes": {"deno": {"path": str(deno.resolve())}}},
            )

    def test_missing_runtime_fails_before_ytdlp_selects_invalid_formats(self) -> None:
        with patch(
            "jang_app.services.youtube_runtime._bundled_deno_candidates",
            return_value=(),
        ), patch("jang_app.services.youtube_runtime.shutil.which", return_value=None), patch.dict(
            "sys.modules", {"deno": None}
        ):
            with self.assertRaises(YouTubeRuntimeError):
                resolve_deno_executable()


if __name__ == "__main__":
    unittest.main()
