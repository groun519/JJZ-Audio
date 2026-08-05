from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    create_update_plan,
)
from jang_app.services.runtime_bootstrap import (
    install_update_runtime_components,
    provision_ai_runtime,
    provision_ai_runtime_offline,
)
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
            self.assertEqual(progress[-1], 100)

    def test_blackwell_install_adds_cu128_profile_after_base_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            paths = replace(paths, runtime_root=root / "app" / "runtime")
            app = ReleaseArtifact("app.exe", 1, "a" * 64, "https://example/app.exe")
            base = ReleaseArtifact("runtime.zip", 10, "b" * 64, "https://example/runtime.zip")
            profile = ReleaseArtifact("cu128.zip", 20, "c" * 64, "https://example/cu128.zip")
            release = ReleaseManifest(
                "0.2.2",
                (
                    ReleaseComponent("application", "0.2.2", "installer", (app,)),
                    ReleaseComponent("ai-runtime", "1", "extract", (base,)),
                    ReleaseComponent("rvc-runtime-cu128", "3", "extract", (profile,)),
                ),
            )

            def download(artifact, destination, *, progress):
                progress(100)
                return destination / artifact.name

            expected = RuntimeInstallation("1", paths.runtime_root, 1)
            with (
                patch("jang_app.services.runtime_bootstrap.fetch_release_manifest", return_value=release),
                patch("jang_app.services.runtime_bootstrap.detect_rvc_runtime_profile", return_value="cu128"),
                patch("jang_app.services.runtime_bootstrap.download_artifact", side_effect=download),
                patch("jang_app.services.runtime_bootstrap.install_runtime_packages", return_value=expected),
                patch("jang_app.services.runtime_bootstrap.install_rvc_runtime_profile_packages") as install_profile,
            ):
                result = provision_ai_runtime(paths)

            self.assertEqual(result, expected)
            self.assertEqual(install_profile.call_args.args[2:4], ("cu128", "3"))

    def test_rocm_activation_failure_automatically_installs_directml_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            paths = replace(paths, runtime_root=root / "app" / "runtime")
            artifact = lambda name: ReleaseArtifact(
                name, 1, "a" * 64, f"https://example/{name}"
            )
            release = ReleaseManifest(
                "0.2.2",
                (
                    ReleaseComponent("application", "0.2.2", "installer", (artifact("app.exe"),)),
                    ReleaseComponent("ai-runtime", "2", "extract", (artifact("runtime.zip"),)),
                    ReleaseComponent("rvc-runtime-rocm-win", "1", "extract", (artifact("rocm.zip"),)),
                    ReleaseComponent("rvc-runtime-directml", "1", "extract", (artifact("directml.zip"),)),
                ),
            )
            expected = RuntimeInstallation("2", paths.runtime_root, 1)
            attempted: list[str] = []

            def install_profile(_packages, _root, profile, _version, **kwargs):
                attempted.append(profile)
                if profile == "rocm-win":
                    raise RuntimeError("HIP unavailable")
                return object()

            with (
                patch("jang_app.services.runtime_bootstrap.fetch_release_manifest", return_value=release),
                patch("jang_app.services.runtime_bootstrap.detect_rvc_runtime_profile", return_value="rocm-win"),
                patch(
                    "jang_app.services.runtime_bootstrap.download_artifact",
                    side_effect=lambda item, destination, *, progress: destination / item.name,
                ),
                patch("jang_app.services.runtime_bootstrap.install_runtime_packages", return_value=expected),
                patch(
                    "jang_app.services.runtime_bootstrap.install_rvc_runtime_profile_packages",
                    side_effect=install_profile,
                ),
            ):
                result = provision_ai_runtime(paths)

            self.assertEqual(result, expected)
            self.assertEqual(attempted, ["rocm-win", "directml"])

    def test_missing_accelerator_packages_records_cpu_fallback_without_runtime_reinstall(self) -> None:
        release = ReleaseManifest(
            "0.2.2",
            (
                ReleaseComponent("application", "0.2.2", "installer", ()),
                ReleaseComponent("ai-runtime", "2", "extract", ()),
            ),
        )
        plan = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cu118",
            installed_rvc_profile_version="2",
        )

        with (
            patch("jang_app.services.runtime_bootstrap.install_runtime_packages") as install,
            patch(
                "jang_app.services.runtime_bootstrap.mark_rvc_runtime_fallback",
                return_value=object(),
            ) as mark_fallback,
        ):
            result = install_update_runtime_components(plan, (), Path("runtime"))

        install.assert_not_called()
        mark_fallback.assert_called_once()
        self.assertEqual(len(result), 1)

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
