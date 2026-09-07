from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleaseSystemFootprintGateTests(unittest.TestCase):
    def test_readiness_routes_installation_through_system_footprint_gate(self) -> None:
        source = (PROJECT_ROOT / "scripts" / "verify_release_readiness.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('"verify_system_footprint.ps1"', source)
        self.assertIn("SystemFootprintEvidencePath", source)
        self.assertNotIn('"verify_release_installation.ps1") `', source)

    def test_system_footprint_gate_tracks_protected_windows_state(self) -> None:
        source = (PROJECT_ROOT / "scripts" / "verify_system_footprint.ps1").read_text(
            encoding="utf-8"
        )

        for marker in (
            "user_environment",
            "machine_environment",
            "python_commands",
            "python_registry",
            "gpu_drivers",
            "services",
            "startup_entries",
            "jjzero_file_associations",
        ):
            self.assertIn(marker, source)
        self.assertIn("verify_release_installation.ps1", source)
        self.assertIn("changed_sections", source)


if __name__ == "__main__":
    unittest.main()
