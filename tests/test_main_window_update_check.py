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
    def test_combined_update_stages_runtime_for_the_new_app_before_installer_launch(
        self,
    ) -> None:
        plan = _runtime_update_plan(application_required=True)
        downloaded = (Path("setup.exe"), Path("runtime.zip"))
        window = SimpleNamespace(
            _downloaded_update_plan=plan,
            _downloaded_update=downloaded,
            _update_dialog=None,
            _launch_downloaded_installer_or_restart=Mock(),
        )

        with (
            patch.object(
                main_window,
                "APP_PATHS",
                SimpleNamespace(cache_dir=Path("cache")),
            ),
            patch.object(
                main_window,
                "stage_pending_component_update",
            ) as stage,
        ):
            MainWindow._install_downloaded_update(window)

        stage.assert_called_once_with(Path("cache"), plan, downloaded)
        window._launch_downloaded_installer_or_restart.assert_called_once_with()

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
            plan = _runtime_update_plan(
                application_required=True,
                runtime_required=False,
            )
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
                patch.object(
                    main_window,
                    "start_detached_command",
                    return_value=True,
                ) as launch,
                patch.object(main_window.QApplication, "quit"),
            ):
                MainWindow._launch_downloaded_installer_or_restart(window)

            self.assertTrue((update / UPDATE_CLEANUP_MARKER).is_file())
            launch.assert_called_once_with(
                (
                    str(installer),
                    "/SILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/CLOSEAPPLICATIONS",
                    "/JJZEROUPDATE",
                ),
                cwd=installer.parent,
            )
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
            True,
            "JJZero Software",
            certificate_sha256="c" * 64,
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

    def test_new_manifest_replaces_an_already_visible_update(self) -> None:
        old = _runtime_update_plan(application_required=True)
        new_release = ReleaseManifest(
            "0.3.2",
            (
                ReleaseComponent(
                    "application",
                    "0.3.2",
                    "installer",
                    old.release.application.artifacts,
                ),
            ),
        )
        new = UpdatePlan(
            new_release,
            application_required=True,
            runtime_required=False,
        )
        host = SimpleNamespace(
            _update_manifest_etag="old",
            _update_manifest_last_modified="old",
            _available_update_plan=old,
            _apply_release_feature_policy=Mock(),
            update_status_button=Mock(),
            _position_update_status=Mock(),
        )

        MainWindow._apply_update_check_outcome(
            host,
            main_window.UpdateCheckOutcome(new, '"new"', "new-date"),
        )

        self.assertIs(host._available_update_plan, new)
        host.update_status_button.set_available.assert_called_once_with(
            "0.3.2",
            runtime_only=False,
        )

    def test_corrected_manifest_can_clear_a_visible_update(self) -> None:
        old = _runtime_update_plan(application_required=True)
        current = UpdatePlan(
            old.release,
            application_required=False,
            runtime_required=False,
        )
        host = SimpleNamespace(
            _update_manifest_etag="old",
            _update_manifest_last_modified="old",
            _available_update_plan=old,
            _apply_release_feature_policy=Mock(),
            update_status_button=Mock(),
            _position_update_status=Mock(),
        )

        MainWindow._apply_update_check_outcome(
            host,
            main_window.UpdateCheckOutcome(current, '"fixed"', "fixed-date"),
        )

        self.assertIsNone(host._available_update_plan)
        host.update_status_button.hide.assert_called_once_with()

    def test_not_modified_check_keeps_the_visible_update(self) -> None:
        old = _runtime_update_plan(application_required=True)
        host = SimpleNamespace(
            _update_manifest_etag="old",
            _update_manifest_last_modified="old",
            _available_update_plan=old,
            _apply_release_feature_policy=Mock(),
            update_status_button=Mock(),
            _position_update_status=Mock(),
        )

        MainWindow._apply_update_check_outcome(
            host,
            main_window.UpdateCheckOutcome(
                None,
                '"same"',
                "same-date",
                not_modified=True,
            ),
        )

        self.assertIs(host._available_update_plan, old)
        host.update_status_button.hide.assert_not_called()


def _runtime_update_plan(
    *,
    application_required: bool,
    runtime_required: bool = True,
) -> UpdatePlan:
    app_version = "0.3.1" if application_required else "0.3.0"
    app = ReleaseArtifact(
        "setup.exe",
        1,
        hashlib.sha256(b"installer").hexdigest(),
        "https://example.test/setup.exe",
        True,
        "JJZero Software",
        certificate_sha256="c" * 64,
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
        runtime_required=runtime_required,
    )


if __name__ == "__main__":
    unittest.main()
