from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jang_app.runtime_version import RVC_RUNTIME_PROFILE_VERSIONS
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

    def test_manifest_can_reuse_runtime_assets_from_an_existing_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.2.3-Setup.exe").write_bytes(b"installer")
            package = release / "JJZero-Runtime-2-part01.zip"
            package.write_bytes(b"runtime")
            (release / "runtime-packages.json").write_text(
                json.dumps(
                    {
                        "version": "2",
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

            manifest = create_release_manifest(
                release,
                "0.2.3",
                "2",
                runtime_release_tag="v0.2.2",
            )

            data = json.loads(manifest.read_text(encoding="utf-8"))
            runtime = next(
                component
                for component in data["components"]
                if component["id"] == "ai-runtime"
            )
            self.assertEqual(
                runtime["artifacts"][0]["url"],
                "https://github.com/groun519/JJZ-Audio/releases/download/"
                "v0.2.2/JJZero-Runtime-2-part01.zip",
            )
            self.assertNotIn("url", data["components"][0]["artifacts"][0])

    def test_rejects_invalid_runtime_release_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.2.3-Setup.exe").write_bytes(b"installer")

            with self.assertRaisesRegex(ValueError, "Invalid runtime release tag"):
                create_release_manifest(
                    release,
                    "0.2.3",
                    runtime_release_tag="../../latest",
                )

    def test_requires_an_installer_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                create_release_manifest(Path(temporary), "0.1.0")

    def test_manifest_includes_optional_cu128_runtime_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.2.2-Setup.exe").write_bytes(b"installer")
            package = release / "JJZero-RVC-cu128-1-part01.zip"
            package.write_bytes(b"cu128")
            (release / "rvc-runtime-cu128-packages.json").write_text(
                json.dumps(
                    {
                        "component": "rvc-runtime-cu128",
                        "version": "1",
                        "artifacts": [
                            {
                                "name": package.name,
                                "size": package.stat().st_size,
                                "sha256": hashlib.sha256(b"cu128").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = create_release_manifest(release, "0.2.2")

            data = json.loads(manifest.read_text(encoding="utf-8"))
            profile = next(
                component
                for component in data["components"]
                if component["id"] == "rvc-runtime-cu128"
            )
            self.assertEqual(profile["version"], "1")

    def test_split_runtime_requires_cu118_profile_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.3.0-Setup.exe").write_bytes(b"installer")
            package = release / "JJZero-Runtime-3-part01.zip"
            package.write_bytes(b"runtime")
            (release / "runtime-packages.json").write_text(
                json.dumps(
                    {
                        "component": "ai-runtime",
                        "version": "3",
                        "requires_rvc_profile": True,
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

            with self.assertRaisesRegex(ValueError, "cu118"):
                create_release_manifest(release, "0.3.0", "3")

    def test_manifest_accepts_shared_runtime_with_cu118_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.3.0-Setup.exe").write_bytes(b"installer")
            runtime = release / "JJZero-Runtime-3-part01.zip"
            runtime.write_bytes(b"runtime")
            profile_version = RVC_RUNTIME_PROFILE_VERSIONS["cu118"]
            profile = release / f"JJZero-RVC-cu118-{profile_version}-part01.zip"
            profile.write_bytes(b"cu118")
            (release / "runtime-packages.json").write_text(
                json.dumps(
                    {
                        "component": "ai-runtime",
                        "version": "3",
                        "requires_rvc_profile": True,
                        "artifacts": [
                            {
                                "name": runtime.name,
                                "size": runtime.stat().st_size,
                                "sha256": hashlib.sha256(b"runtime").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (release / "rvc-runtime-cu118-packages.json").write_text(
                json.dumps(
                    {
                        "component": "rvc-runtime-cu118",
                        "version": profile_version,
                        "artifacts": [
                            {
                                "name": profile.name,
                                "size": profile.stat().st_size,
                                "sha256": hashlib.sha256(b"cu118").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = create_release_manifest(release, "0.3.0", "3")

            component_ids = {
                component["id"]
                for component in json.loads(manifest.read_text(encoding="utf-8"))["components"]
            }
            self.assertIn("ai-runtime", component_ids)
            self.assertIn("rvc-runtime-cu118", component_ids)

    def test_manifest_includes_optional_amd_runtime_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.2.2-Setup.exe").write_bytes(b"installer")
            for profile in ("directml", "rocm-win"):
                version = RVC_RUNTIME_PROFILE_VERSIONS[profile]
                package = release / f"JJZero-RVC-{profile}-{version}-part01.zip"
                package.write_bytes(profile.encode())
                (release / f"rvc-runtime-{profile}-packages.json").write_text(
                    json.dumps(
                        {
                            "component": f"rvc-runtime-{profile}",
                            "version": version,
                            "artifacts": [
                                {
                                    "name": package.name,
                                    "size": package.stat().st_size,
                                    "sha256": hashlib.sha256(profile.encode()).hexdigest(),
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            manifest = create_release_manifest(release, "0.2.2")

            component_ids = {
                component["id"]
                for component in json.loads(manifest.read_text(encoding="utf-8"))["components"]
            }
            self.assertIn("rvc-runtime-directml", component_ids)
            self.assertIn("rvc-runtime-rocm-win", component_ids)

    def test_rocm_release_requires_a_directml_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            (release / "JJZero-Audio-0.2.2-Setup.exe").write_bytes(b"installer")
            version = RVC_RUNTIME_PROFILE_VERSIONS["rocm-win"]
            package = release / f"JJZero-RVC-rocm-win-{version}-part01.zip"
            package.write_bytes(b"rocm")
            (release / "rvc-runtime-rocm-win-packages.json").write_text(
                json.dumps(
                    {
                        "component": "rvc-runtime-rocm-win",
                        "version": version,
                        "artifacts": [
                            {
                                "name": package.name,
                                "size": package.stat().st_size,
                                "sha256": hashlib.sha256(b"rocm").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "DirectML fallback"):
                create_release_manifest(release, "0.2.2")

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
