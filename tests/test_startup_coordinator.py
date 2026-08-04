from __future__ import annotations

import logging
import unittest

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.startup_coordinator import StartupCoordinator
from jang_app.qt_app.startup_splash import StartupSplash
from jang_app.services.settings import AppSettings
from jang_app.services.startup_timing import StartupTimeline


class StartupCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_runs_stages_in_order_and_shows_window(self) -> None:
        events: list[str] = []

        class FakeWindow(QWidget):
            def __init__(self, settings: AppSettings) -> None:
                super().__init__()
                events.append(f"window:{settings.theme_mode}")

        coordinator = StartupCoordinator(
            self.app,
            StartupTimeline(),
            _test_logger(),
            splash=StartupSplash(APP_ICON_PATH),
            prepare_environment=lambda: events.append("prepare"),
            settings_loader=lambda: _settings(events),
            window_loader=lambda: _window_type(events, FakeWindow),
        )
        finished = QSignalSpy(coordinator.finished)

        coordinator.start()
        _wait_for_signal(finished)

        self.assertEqual(events, ["prepare", "settings", "load_window", "window:dark"])
        self.assertIsNotNone(coordinator.window)
        self.assertTrue(coordinator.window.isVisible())
        mark_names = tuple(mark.name for mark in coordinator.timeline.marks)
        self.assertIn("storage_ready", mark_names)
        self.assertIn("event_loop_ready", mark_names)
        coordinator.window.close()
        coordinator.splash.close()

    def test_failure_stays_on_splash_with_close_action(self) -> None:
        def fail() -> None:
            raise RuntimeError("storage unavailable")

        coordinator = StartupCoordinator(
            self.app,
            StartupTimeline(),
            _test_logger(),
            splash=StartupSplash(APP_ICON_PATH),
            prepare_environment=fail,
        )
        failed = QSignalSpy(coordinator.failed)

        coordinator.start()
        _wait_for_signal(failed)

        self.assertEqual(failed.at(0)[0], "storage unavailable")
        self.assertEqual(coordinator.splash.stage_label.text(), "STARTUP FAILED")
        self.assertFalse(coordinator.splash.close_button.isHidden())
        coordinator.splash.close()


def _settings(events: list[str]) -> AppSettings:
    events.append("settings")
    return AppSettings(theme_mode="dark")


def _window_type(events: list[str], window_type: type[QWidget]) -> type[QWidget]:
    events.append("load_window")
    return window_type


def _wait_for_signal(spy: QSignalSpy) -> None:
    for _ in range(30):
        if spy.count():
            return
        QTest.qWait(10)
    raise AssertionError("Timed out waiting for startup signal")


def _test_logger() -> logging.Logger:
    logger = logging.getLogger("jang_app.tests.startup")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


if __name__ == "__main__":
    unittest.main()
