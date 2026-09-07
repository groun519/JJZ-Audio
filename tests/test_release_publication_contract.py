from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleasePublicationContractTests(unittest.TestCase):
    def test_publication_requires_previous_installer_and_forwards_evidence(self) -> None:
        source = (PROJECT_ROOT / "scripts" / "publish_github_release.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("[Parameter(Mandatory = $true)]", source)
        self.assertIn("PreviousInstallerPath = $previousInstaller", source)
        self.assertIn("SystemFootprintEvidencePath", source)

    def test_publication_requires_pushed_source_and_verifies_public_assets(self) -> None:
        source = (PROJECT_ROOT / "scripts" / "publish_github_release.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("HEAD does not match origin/main", source)
        self.assertIn("release download", source)
        self.assertIn("Get-AuthenticodeSignature", source)
        self.assertIn("releases/latest", source)
        self.assertIn('refs/tags/$tag^{}', source)


if __name__ == "__main__":
    unittest.main()
