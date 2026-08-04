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
            application = data["components"][0]
            self.assertEqual(application["id"], "application")
            self.assertEqual(application["artifacts"][0]["name"], installer.name)
            self.assertEqual(application["artifacts"][0]["size"], len(b"installer"))
            self.assertEqual(
                application["artifacts"][0]["sha256"],
                hashlib.sha256(b"installer").hexdigest(),
            )

    def test_manifest_includes_versioned_runtime_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.1.0-Setup.exe").write_bytes(b"installer")
            package = release / "JJZero-Runtime-7-part01.zip"
            package.write_bytes(b"runtime")
            (release / "runtime-packages.json").write_text(
                json.dumps(
                    {
                        "version": "7",
                        "artifacts": [
                            {
                                "name": package.name,
                                "size": package.stat().st_size,
                                "sha256": hashlib.sha256(b"runtime").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = create_release_manifest(release, "0.1.0", "7")

            data = json.loads(manifest.read_text(encoding="utf-8"))
            runtime = data["components"][1]
            self.assertEqual(runtime["id"], "ai-runtime")
            self.assertEqual(runtime["version"], "7")
            self.assertEqual(runtime["artifacts"][0]["name"], package.name)

    def test_requires_an_installer_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                create_release_manifest(Path(temporary), "0.1.0")

    def test_rejects_runtime_index_when_package_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.1.0-Setup.exe").write_bytes(b"installer")
            package = release / "JJZero-Runtime-1-part01.zip"
            package.write_bytes(b"changed")
            (release / "runtime-packages.json").write_text(
                json.dumps(
                    {
                        "version": "1",
                        "artifacts": [
                            {
                                "name": package.name,
                                "size": 3,
                                "sha256": hashlib.sha256(b"old").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                create_release_manifest(release, "0.1.0", "1")

    def test_signed_manifest_requires_expected_publisher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.1.0-Setup.exe").write_bytes(b"installer")

            manifest = create_release_manifest(
                release,
                "0.1.0",
                signing_publisher="JJZero Software",
            )

            data = json.loads(manifest.read_text(encoding="utf-8"))
            signing = data["components"][0]["artifacts"][0]["authenticode"]
            self.assertTrue(signing["required"])
            self.assertEqual(signing["publisher"], "JJZero Software")


if __name__ == "__main__":
    unittest.main()
