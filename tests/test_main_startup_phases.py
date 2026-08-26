from __future__ import annotations

import unittest
from pathlib import Path


class MainStartupPhaseTests(unittest.TestCase):
    def test_blocking_setup_phases_have_explicit_timing_marks(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "jang_app"
            / "qt_app"
            / "main.py"
        ).read_text(encoding="utf-8")

        names = (
            "application_created",
            "paths_discovered",
            "runtime_recovery_checked",
            "runtime_overlay_repaired",
            "setup_started",
            "setup_finished",
            "hardware_diagnostics_started",
            "hardware_diagnostics_finished",
        )
        for name in names:
            self.assertIn(f'startup.mark("{name}")', source)
        self.assertLess(
            source.index('startup.mark("application_created")'),
            source.index("discover_app_paths(package_root)"),
        )
        self.assertLess(
            source.index("logger = get_logger()"),
            source.index("recover_runtime_installations(setup_paths.runtime_root)"),
        )


if __name__ == "__main__":
    unittest.main()
