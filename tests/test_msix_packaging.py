from __future__ import annotations

import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_TEMPLATE = ROOT / "packaging" / "msix" / "AppxManifest.xml.in"
BUILD_SCRIPT = ROOT / "scripts" / "build_msix.ps1"


class MsixPackagingTests(unittest.TestCase):
    def test_manifest_template_is_valid_after_replacement(self) -> None:
        manifest = MANIFEST_TEMPLATE.read_text(encoding="utf-8")
        replacements = {
            "@@IDENTITY_NAME@@": "JJZeroAudio.Test",
            "@@PUBLISHER@@": "CN=JJZero Test",
            "@@PACKAGE_VERSION@@": "1.2.8.0",
            "@@DISPLAY_NAME@@": "JJZero Audio",
            "@@PUBLISHER_DISPLAY_NAME@@": "JJZero",
        }
        for token, value in replacements.items():
            manifest = manifest.replace(token, value)

        root = ElementTree.fromstring(manifest)
        namespace = {"appx": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}
        identity = root.find("appx:Identity", namespace)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.attrib["Version"], "1.2.8.0")
        self.assertEqual(identity.attrib["ProcessorArchitecture"], "x64")

    def test_store_build_stages_channel_marker_and_excludes_runtime(self) -> None:
        script = BUILD_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('channel = "store"', script)
        self.assertIn('Where-Object { $_.Name -ne "runtime" }', script)
        self.assertIn('-Encoding ASCII', script)
        self.assertIn('verify_msix_package.ps1', script)


if __name__ == "__main__":
    unittest.main()
