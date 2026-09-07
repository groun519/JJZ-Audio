from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsBuildEnvironmentTests(unittest.TestCase):
    def test_pyinstaller_runs_with_an_isolated_path_and_restores_the_host(self) -> None:
        source = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("$originalPath = $env:PATH", source)
        self.assertIn("$env:PATH = $isolatedBuildPath", source)
        self.assertIn("$env:PATH = $originalPath", source)
        self.assertIn('Join-Path $env:SystemRoot "System32"', source)

    def test_distribution_rejects_host_windows_runtime_dlls(self) -> None:
        source = (ROOT / "scripts" / "verify_distribution.py").read_text(encoding="utf-8")

        self.assertIn('"ucrtbase.dll"', source)
        self.assertIn('glob("api-ms-win-*.dll")', source)
        self.assertIn("host Windows runtime DLL", source)


if __name__ == "__main__":
    unittest.main()
