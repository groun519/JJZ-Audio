from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jang_app.qt_app import main_window
from jang_app.qt_app.main_window import MainWindow, _check_for_updates
from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    ReleaseManifestCheck,
    UpdatePlan,
)
from jang_app.services.update_cache import UPDATE_CLEANUP_MARKER


class MainWindowUpdateCheckTests(unittest.TestCase):
    def test_runtime_only_completion_discards_the_whole_update_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.0"
            package = update / "runtime.zip"
            partial = update / "obsolete.zip.part"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"runtime")
            partial.write_bytes(b"partial")
            plan = _runtime_update_plan(application_required=False)
            window = SimpleNamespace(
                _downloaded_update=(package,),
                _launch_downloaded_installer_or_restart=Mock(),
                _logger=Mock(),
            )

            with patch.object(
                main_window,
                "APP_PATHS",
                SimpleNamespace(cache_dir=cache),
            ):
                MainWindow._finish_runtime_update_install(window, plan)

            self.assertFalse(update.exists())
            window._launch_downloaded_installer_or_restart.assert_called_once_with()

    def test_successful_installer_launch_marks_update_for_next_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.1"
            installer = update / "setup.exe"
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b"installer")
            plan = _runtime_update_plan(application_required=True)
            window = SimpleNamespace(
                _downloaded_update=(installer,),
                _downloaded_update_plan=plan,
                _update_dialog=None,
                _set_update_download_failed=Mock(),
                _logger=Mock(),
            )
            application = SimpleNamespace(_jjzero_mutex_handle=123)

            with (
                patch.object(
                    main_window,
                    "APP_PATHS",
                    SimpleNamespace(cache_dir=cache),
                ),
                patch.object(main_window.QApplication, "instance", return_value=application),
                patch.object(main_window, "close_app_mutex", return_value=True) as close_mutex,
                patch.object(main_window, "start_detached_command", return_value=True),
                patch.object(main_window.QApplication, "quit"),
            ):
                MainWindow._launch_downloaded_installer_or_restart(window)

            self.assertTrue((update / UPDATE_CLEANUP_MARKER).is_file())
            close_mutex.assert_called_once_with(123)
            self.assertIsNone(application._jjzero_mutex_handle)

    def test_failed_installer_launch_does_not_mark_update_for_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.1"
            installer = update / "setup.exe"
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b"installer")
            plan = _runtime_update_plan(application_required=True)
            window = SimpleNamespace(
                _downloaded_update=(installer,),
                _downloaded_update_plan=plan,
                _update_dialog=None,
                _set_update_download_failed=Mock(),
                _logger=Mock(),
            )
            application = SimpleNamespace(_jjzero_mutex_handle=456)

            with (
                patch.object(
                    main_window,
                    "APP_PATHS",
                    SimpleNamespace(cache_dir=cache),
                ),
                patch.object(main_window.QApplication, "instance", return_value=application),
                patch.object(main_window, "close_app_mutex", return_value=True),
                patch.object(main_window, "create_app_mutex", return_value=789),
                patch.object(main_window, "start_detached_command", return_value=False),
                patch.object(main_window.QApplication, "quit"),
            ):
                MainWindow._launch_downloaded_installer_or_restart(window)

            self.assertFalse((update / UPDATE_CLEANUP_MARKER).exists())
            self.assertEqual(application._jjzero_mutex_handle, 789)

    def test_builds_update_outcome_and_preserves_cache_validators(self) -> None:
        artifact = ReleaseArtifact(
            "app.exe",
            3,
            hashlib.sha256(b"app").hexdigest(),
            "https://example.test/app.exe",
        )
        release = ReleaseManifest(
            "99.0.0",
            (ReleaseComponent("application", "99.0.0", "installer", (artifact,)),),
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


def _runtime_update_plan(*, application_required: bool) -> UpdatePlan:
    app_version = "0.3.1" if application_required else "0.3.0"
    app = ReleaseArtifact(
        "setup.exe",
        1,
        hashlib.sha256(b"installer").hexdigest(),
        "https://example.test/setup.exe",
    )
    runtime = ReleaseArtifact(
        "runtime.zip",
        1,
        hashlib.sha256(b"runtime").hexdigest(),
        "https://example.test/runtime.zip",
    )
    release = ReleaseManifest(
        app_version,
        (
            ReleaseComponent("application", app_version, "installer", (app,)),
            ReleaseComponent("ai-runtime", "4", "extract", (runtime,)),
        ),
    )
    return UpdatePlan(
        release,
        application_required=application_required,
        runtime_required=True,
    )


if __name__ == "__main__":
    unittest.main()
