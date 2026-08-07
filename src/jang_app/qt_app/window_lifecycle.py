from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu, QWidget


_LOGGER = logging.getLogger("jang_app")
_EXPLICIT_WINDOW_PROPERTY = "allowTopLevelWindow"
_FRAMEWORK_WINDOW_TYPES = frozenset(
    (
        Qt.WindowType.Popup,
        Qt.WindowType.ToolTip,
        Qt.WindowType.SplashScreen,
    )
)


class WindowLifecycleGuard(QObject):
    """Blocks accidental bare widgets from flashing as independent windows."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self._blocked_count = 0
        self._last_blocked = ""

    @property
    def blocked_count(self) -> int:
        return self._blocked_count

    @property
    def last_blocked(self) -> str:
        return self._last_blocked

    def eventFilter(self, watched, event):  # noqa: N802
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
            and not self.is_expected_window(watched)
        ):
            description = _window_description(watched)
            self._blocked_count += 1
            self._last_blocked = description
            _LOGGER.error("Blocked unexpected top-level widget: %s", description)
            watched.hide()
            return True
        return False

    @staticmethod
    def is_expected_window(widget: QWidget) -> bool:
        if isinstance(widget, (QMainWindow, QDialog, QMenu)):
            return True
        if bool(widget.property(_EXPLICIT_WINDOW_PROPERTY)):
            return True
        return widget.windowType() in _FRAMEWORK_WINDOW_TYPES


def install_window_lifecycle_guard(application: QApplication) -> WindowLifecycleGuard:
    existing = getattr(application, "_jjzero_window_lifecycle_guard", None)
    if isinstance(existing, WindowLifecycleGuard):
        return existing
    guard = WindowLifecycleGuard(application)
    application.installEventFilter(guard)
    application._jjzero_window_lifecycle_guard = guard
    return guard


def _window_description(widget: QWidget) -> str:
    return (
        f"class={type(widget).__name__} "
        f"object={widget.objectName() or '-'} "
        f"title={widget.windowTitle() or '-'}"
    )
