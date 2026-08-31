from __future__ import annotations

import unittest
from unittest.mock import patch

from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    UpdateError,
    create_update_plan,
    parse_release_manifest,
)


class ReleasePlatformCompatibilityTests(unittest.TestCase):
    def test_parser_rejects_release_for_another_architecture(self) -> None:
        with patch(
            "jang_app.services.app_update._host_architecture",
            return_value="x64",
        ):
            with self.assertRaisesRegex(UpdateError, "requires arm64"):
                parse_release_manifest(
                    _manifest_data(architecture="arm64"),
                    "https://example.test/latest.json",
                )

    def test_parser_rejects_release_for_newer_windows(self) -> None:
        with (
            patch(
                "jang_app.services.app_update._host_architecture",
                return_value="x64",
            ),
            patch(
                "jang_app.services.app_update._host_windows_version",
                return_value=(10, 0, 14393),
            ),
        ):
            with self.assertRaisesRegex(UpdateError, "10.0.17763 or newer"):
                parse_release_manifest(
                    _manifest_data(),
                    "https://example.test/latest.json",
                )

    def test_parser_preserves_compatible_platform_contract(self) -> None:
        with (
            patch(
                "jang_app.services.app_update._host_architecture",
                return_value="x64",
            ),
            patch(
                "jang_app.services.app_update._host_windows_version",
                return_value=(10, 0, 19045),
            ),
        ):
            release = parse_release_manifest(
                _manifest_data(),
                "https://example.test/latest.json",
            )

        self.assertEqual(release.architecture, "x64")
        self.assertEqual(release.minimum_windows, "10.0.17763")

    def test_parser_rejects_malformed_platform_contract(self) -> None:
        invalid_architecture = _manifest_data(architecture="x86")
        invalid_windows = _manifest_data(minimum_windows="Windows 10")

        with self.assertRaisesRegex(UpdateError, "architecture"):
            parse_release_manifest(
                invalid_architecture,
                "https://example.test/latest.json",
            )
        with self.assertRaisesRegex(UpdateError, "Windows version"):
            parse_release_manifest(
                invalid_windows,
                "https://example.test/latest.json",
            )

    def test_update_plan_checks_manually_constructed_manifest(self) -> None:
        artifact = ReleaseArtifact(
            "setup.exe",
            1,
            "a" * 64,
            "https://example.test/setup.exe",
        )
        release = ReleaseManifest(
            "9.0.0",
            (ReleaseComponent("application", "9.0.0", "installer", (artifact,)),),
            architecture="arm64",
        )

        with patch(
            "jang_app.services.app_update._host_architecture",
            return_value="x64",
        ):
            with self.assertRaisesRegex(UpdateError, "requires arm64"):
                create_update_plan(release, current_version="0.1.0")


def _manifest_data(
    *,
    architecture: str = "x64",
    minimum_windows: str = "10.0.17763",
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "product": "JJZero Audio",
        "version": "9.0.0",
        "architecture": architecture,
        "minimum_windows": minimum_windows,
        "components": [
            {
                "id": "application",
                "version": "9.0.0",
                "install_mode": "installer",
                "artifacts": [
                    {
                        "name": "setup.exe",
                        "size": 1,
                        "sha256": "a" * 64,
                        "url": "https://example.test/setup.exe",
                    }
                ],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
