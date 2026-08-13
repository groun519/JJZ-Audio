from __future__ import annotations

import logging
import weakref

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu, QWidget


_LOGGER = logging.getLogger("jang_app")
_EXPLICIT_WINDOW_PROPERTY = "allowTopLevelWindow"
_PARENTING_RETRY_INTERVAL_MS = 40
_PARENTING_RETRY_COUNT = 5
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
        self._pending_widget_ids: set[int] = set()

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
            watched.hide()
            self._resolve_after_parenting(watched)
            return True
        return False

    def _resolve_after_parenting(self, widget: QWidget) -> None:
        widget_id = id(widget)
        if widget_id in self._pending_widget_ids:
            return
        self._pending_widget_ids.add(widget_id)
        widget_reference = weakref.ref(widget)
        QTimer.singleShot(
            0,
            lambda: self._finish_resolution(
                widget_id,
                widget_reference,
                _PARENTING_RETRY_COUNT,
            ),
        )

    def _finish_resolution(
        self,
        widget_id: int,
        widget_reference,
        retries_remaining: int,
    ) -> None:
        widget = widget_reference()
        if widget is None:
            self._pending_widget_ids.discard(widget_id)
            return
        try:
            if not widget.isWindow() or self.is_expected_window(widget):
                self._pending_widget_ids.discard(widget_id)
                widget.show()
                return
            if retries_remaining > 0:
                QTimer.singleShot(
                    _PARENTING_RETRY_INTERVAL_MS,
                    lambda: self._finish_resolution(
                        widget_id,
                        widget_reference,
                        retries_remaining - 1,
                    ),
                )
                return
            description = _window_description(widget)
        except RuntimeError:
            self._pending_widget_ids.discard(widget_id)
            return
        self._pending_widget_ids.discard(widget_id)
        self._blocked_count += 1
        self._last_blocked = description
        _LOGGER.error("Blocked unexpected top-level widget: %s", description)

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


def allow_top_level_window(widget: QWidget) -> None:
    """Mark an intentional non-dialog window as safe for the lifecycle guard."""
    widget.setProperty(_EXPLICIT_WINDOW_PROPERTY, True)


def _window_description(widget: QWidget) -> str:
    return (
        f"class={type(widget).__name__} "
        f"object={widget.objectName() or '-'} "
        f"title={widget.windowTitle() or '-'}"
    )
