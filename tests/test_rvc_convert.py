from __future__ import annotations

import os
import unittest
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.pipeline.rvc_convert import _build_rvc_environment


class RvcConvertTests(unittest.TestCase):
    def test_environment_prefers_bundled_ffmpeg(self) -> None:
        rvc_root = Path("C:/rvc")

        environment = _build_rvc_environment(rvc_root)

        path_parts = environment["PATH"].split(os.pathsep)
        self.assertEqual(path_parts[0], str(FFMPEG_BIN_DIR))
        self.assertEqual(path_parts[1], str(rvc_root))
        self.assertEqual(path_parts[2], str(rvc_root / "runtime"))


if __name__ == "__main__":
    unittest.main()
