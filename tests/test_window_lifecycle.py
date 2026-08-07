from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QWidget

from jang_app.qt_app.window_lifecycle import (
    WindowLifecycleGuard,
    install_window_lifecycle_guard,
)


class WindowLifecycleGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        existing = getattr(self.app, "_jjzero_window_lifecycle_guard", None)
        if isinstance(existing, WindowLifecycleGuard):
            self.app.removeEventFilter(existing)
            delattr(self.app, "_jjzero_window_lifecycle_guard")

    def tearDown(self) -> None:
        existing = getattr(self.app, "_jjzero_window_lifecycle_guard", None)
        if isinstance(existing, WindowLifecycleGuard):
            self.app.removeEventFilter(existing)
            delattr(self.app, "_jjzero_window_lifecycle_guard")

    def test_parentless_label_is_blocked_before_it_can_remain_visible(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        label = QLabel("Accidental window")
        label.setObjectName("TransientLabel")

        with self.assertLogs("jang_app", level="ERROR") as captured:
            label.show()
            self.app.processEvents()

        self.assertFalse(label.isVisible())
        self.assertEqual(guard.blocked_count, 1)
        self.assertIn("TransientLabel", guard.last_blocked)
        self.assertIn("Blocked unexpected top-level widget", captured.output[0])
        label.close()

    def test_normal_application_windows_and_framework_popups_are_allowed(self) -> None:
        guard = WindowLifecycleGuard(self.app)
        dialog = QDialog()
        menu = QMenu()
        splash = QWidget(
            None,
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint,
        )

        self.assertTrue(guard.is_expected_window(dialog))
        self.assertTrue(guard.is_expected_window(menu))
        self.assertTrue(guard.is_expected_window(splash))

    def test_explicit_custom_window_opt_in_is_allowed(self) -> None:
        guard = WindowLifecycleGuard(self.app)
        custom_window = QWidget()
        custom_window.setProperty("allowTopLevelWindow", True)

        self.assertTrue(guard.is_expected_window(custom_window))

    def test_installation_is_idempotent(self) -> None:
        first = install_window_lifecycle_guard(self.app)
        second = install_window_lifecycle_guard(self.app)

        self.assertIs(first, second)
