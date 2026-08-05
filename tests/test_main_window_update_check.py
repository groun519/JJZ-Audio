from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from jang_app.qt_app.main_window import _check_for_updates
from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    ReleaseManifestCheck,
)


class MainWindowUpdateCheckTests(unittest.TestCase):
    def test_builds_update_outcome_and_preserves_cache_validators(self) -> None:
        artifact = ReleaseArtifact(
            "app.exe",
            3,
            hashlib.sha256(b"app").hexdigest(),
            "https://example.test/app.exe",
        )
        release = ReleaseManifest(
            "0.3.0",
            (ReleaseComponent("application", "0.3.0", "installer", (artifact,)),),
        )
        progress: list[int] = []

        with (
            patch(
                "jang_app.qt_app.main_window.fetch_release_manifest_if_changed",
                return_value=ReleaseManifestCheck(release, '"etag"', "modified"),
            ),
            patch(
                "jang_app.qt_app.main_window.installed_runtime_version",
                return_value="1",
            ),
            patch(
                "jang_app.qt_app.main_window.installed_rvc_runtime_profile",
                return_value=None,
            ),
            patch(
                "jang_app.qt_app.main_window.detect_rvc_runtime_profile",
                return_value="cu118",
            ),
        ):
            outcome = _check_for_updates(
                "https://example.test/latest.json",
                progress.append,
                etag='"previous"',
            )

        self.assertTrue(outcome.plan.required if outcome.plan else False)
        self.assertEqual(outcome.etag, '"etag"')
        self.assertEqual(progress, [10, 100])


if __name__ == "__main__":
    unittest.main()
