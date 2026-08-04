from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.app_update import ReleaseArtifact, ReleaseComponent, ReleaseManifest
from jang_app.services.runtime_bootstrap import provision_ai_runtime, provision_ai_runtime_offline
from jang_app.services.runtime_installation import RuntimeInstallation


class RuntimeBootstrapTests(unittest.TestCase):
    def test_downloads_all_runtime_parts_before_installing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            paths = replace(paths, runtime_root=root / "app" / "runtime")
            artifacts = (
                ReleaseArtifact("part1.zip", 10, "a" * 64, "https://example/part1.zip"),
                ReleaseArtifact("part2.zip", 20, "b" * 64, "https://example/part2.zip"),
            )
            release = ReleaseManifest(
                "0.2.0",
                (
                    ReleaseComponent("application", "0.2.0", "installer", (artifacts[0],)),
                    ReleaseComponent("ai-runtime", "4", "extract", artifacts),
                ),
            )
            downloaded: list[str] = []

            def download(artifact, destination, *, progress):
                downloaded.append(artifact.name)
                progress(100)
                return destination / artifact.name

            expected = RuntimeInstallation("4", paths.runtime_root, 2)
            progress: list[int] = []
            with (
                patch("jang_app.services.runtime_bootstrap.fetch_release_manifest", return_value=release),
                patch("jang_app.services.runtime_bootstrap.download_artifact", side_effect=download),
                patch("jang_app.services.runtime_bootstrap.install_runtime_packages", return_value=expected),
            ):
                result = provision_ai_runtime(paths, progress=progress.append)

            self.assertEqual(result, expected)
            self.assertEqual(downloaded, ["part1.zip", "part2.zip"])
            self.assertEqual(progress[-1], 70)

    def test_offline_runtime_rejects_changed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            package = root / "part01.zip"
            package.write_bytes(b"changed")
            index = root / "runtime-packages.json"
            index.write_text(
                '{"schema_version": 1, "component": "ai-runtime", "version": "1", '
                '"artifacts": [{"name": "part01.zip", "size": 3, '
                '"sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}',
                encoding="utf-8",
            )

            with self.assertRaises(Exception):
                provision_ai_runtime_offline(paths, index)


if __name__ == "__main__":
    unittest.main()
