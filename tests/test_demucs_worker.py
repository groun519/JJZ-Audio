from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.pipeline import separate
class DemucsRuntimeTests(unittest.TestCase):
    def test_frozen_separation_uses_the_shared_ai_runtime(self) -> None:
        source = Path("input.wav")
        output = Path("output")

        frozen_paths = replace(separate.APP_PATHS, is_frozen=True)
        with (
            patch.object(separate, "APP_PATHS", frozen_paths),
            patch.object(
                separate,
                "RVC_PYTHON_EXE",
                Path(r"C:\Program Files\JJZero\runtime\rvc\runtime\python.exe"),
            ),
        ):
            command = separate._build_demucs_command(source, output, "htdemucs")

        self.assertEqual(
            command[:3],
            [
                r"C:\Program Files\JJZero\runtime\rvc\runtime\python.exe",
                "-m",
                "demucs",
            ],
        )
        self.assertEqual(command[-1], str(source))

    def test_frozen_worker_uses_packaged_torch_cache(self) -> None:
        frozen_paths = replace(separate.APP_PATHS, is_frozen=True)
        with patch.object(separate, "APP_PATHS", frozen_paths):
            environment = separate._build_demucs_environment()

        self.assertIsNotNone(environment)
        self.assertEqual(
            environment["TORCH_HOME"],
            str(separate.DEMUCS_RUNTIME_DIR / "torch"),
        )

if __name__ == "__main__":
    unittest.main()
