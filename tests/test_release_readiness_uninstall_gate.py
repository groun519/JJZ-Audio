from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessUninstallGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readiness = (ROOT / "scripts" / "verify_release_readiness.ps1").read_text(
            encoding="utf-8-sig"
        )
        cls.gate = (ROOT / "scripts" / "verify_release_installation.ps1").read_text(
            encoding="utf-8-sig"
        )
        cls.complete = (ROOT / "scripts" / "verify_complete_uninstall.ps1").read_text(
            encoding="utf-8-sig"
        )
        cls.installer = (ROOT / "scripts" / "verify_installer.ps1").read_text(
            encoding="utf-8-sig"
        )

    def test_readiness_requires_a_previous_installer(self) -> None:
        self.assertIn("[Parameter(Mandatory = $true)]", self.readiness)
        self.assertIn("[string]$PreviousInstallerPath", self.readiness)
        self.assertIn("verify_release_installation.ps1", self.readiness)

    def test_gate_rejects_same_or_newer_baselines(self) -> None:
        self.assertIn(
            "[version]$previousVersion -ge [version]$version",
            self.gate,
        )

    def test_gate_builds_and_removes_a_unique_verification_installer(self) -> None:
        self.assertIn('"/DVerificationBuild"', self.gate)
        self.assertIn('"$version-Gate-$testId"', self.gate)
        self.assertIn("[IO.File]::Delete($resolvedArtifact)", self.gate)
        self.assertIn('"$releaseRoot\\"', self.gate)

    def test_public_installer_and_verification_installer_have_separate_roles(self) -> None:
        self.assertIn('"-InstallerPath", $installer', self.gate)
        self.assertIn('"-PreviousInstallerPath", $previousInstaller', self.gate)
        self.assertEqual(
            self.gate.count('@("-InstallerPath", $verificationInstaller, "-Scenario", "All")'),
            2,
        )

    def test_complete_all_includes_safe_and_refused_layouts(self) -> None:
        for scenario in (
            "PreserveWork",
            "DeleteWork",
            "MissingGenerated",
            "ProtectedAppState",
            "OverlappingRoots",
            "BrokenSettings",
        ):
            self.assertIn(f'"{scenario}"', self.complete)
        self.assertIn(
            '"*Complete Removal could not remove configured storage:*"',
            self.complete,
        )

    def test_release_gate_has_no_skip_for_install_or_removal(self) -> None:
        self.assertNotIn("SkipInstaller", self.readiness)
        self.assertNotIn("SkipUninstall", self.readiness)
        self.assertNotIn("SkipInstaller", self.gate)
        self.assertNotIn("SkipUninstall", self.gate)

    def test_installer_verification_is_module_and_window_independent(self) -> None:
        self.assertIn("function Get-Sha256Hex", self.installer)
        self.assertNotIn("Get-FileHash", self.installer)
        self.assertIn('$env:QT_QPA_PLATFORM = "offscreen"', self.installer)
        self.assertIn("function Stop-InstalledAppRelaunch", self.installer)
        self.assertIn("$actualPath.Equals(", self.installer)
        self.assertIn("[void]$updateProcess.WaitForExit()", self.installer)


if __name__ == "__main__":
    unittest.main()
