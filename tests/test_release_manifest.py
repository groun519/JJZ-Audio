from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.create_release_manifest import create_release_manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_contains_installer_hash_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            installer = release / "JJZero-Audio-0.1.0-Setup.exe"
            installer.write_bytes(b"installer")

            manifest = create_release_manifest(release, "0.1.0")

            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "0.1.0")
            self.assertEqual(data["artifacts"][0]["name"], installer.name)
            self.assertEqual(data["artifacts"][0]["size"], len(b"installer"))
            self.assertEqual(
                data["artifacts"][0]["sha256"],
                hashlib.sha256(b"installer").hexdigest(),
            )

    def test_requires_an_installer_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                create_release_manifest(Path(temporary), "0.1.0")


if __name__ == "__main__":
    unittest.main()
