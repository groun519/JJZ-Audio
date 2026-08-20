from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "JJZeroAudio.spec"


class PyInstallerPackagingTests(unittest.TestCase):
    def test_app_only_build_excludes_component_runtime_packages(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")

        self.assertIn(
            'excludes=["demucs", "torch", "torchaudio", "torchvision"]',
            spec,
        )


if __name__ == "__main__":
    unittest.main()
