from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.services.processing_queue import (
    ProcessingQueue,
    ProcessingTask,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
)


class TaskAttentionController(QObject):
    """Requests taskbar attention when background processing finishes."""

    def __init__(
        self,
        queue: ProcessingQueue,
        window: QWidget,
        *,
        application: QApplication | None = None,
        alert: Callable[[], None] | None = None,
        is_foreground: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(window)
        resolved_application = application or QApplication.instance()
        if resolved_application is None:
            raise RuntimeError("Task attention requires a QApplication.")
        self._queue = queue
        self._window = window
        self._application = resolved_application
        self._alert = alert or (lambda: self._application.alert(self._window, 0))
        self._is_foreground = is_foreground or self._window_is_foreground
        self._known_statuses: dict[str, str] = {}
        self._attention_pending = False
        self._closed = False

        self._window.installEventFilter(self)
        self._application.applicationStateChanged.connect(
            self._on_application_state_changed
        )
        self._queue.subscribe(self._on_tasks_changed)

    def acknowledge(self) -> None:
        self._attention_pending = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.unsubscribe(self._on_tasks_changed)
        self._window.removeEventFilter(self)
        try:
            self._application.applicationStateChanged.disconnect(
                self._on_application_state_changed
            )
        except (RuntimeError, TypeError):
            pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._window and event.type() == QEvent.Type.WindowActivate:
            self.acknowledge()
        return super().eventFilter(watched, event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        next_statuses = {task.task_id: task.status for task in tasks}
        should_alert = any(
            self._known_statuses.get(task.task_id) == TASK_RUNNING
            and task.status in {TASK_COMPLETED, TASK_FAILED}
            for task in tasks
        )
        self._known_statuses = next_statuses
        if (
            should_alert
            and not self._attention_pending
            and not self._is_foreground()
        ):
            self._attention_pending = True
            self._alert()

    def _on_application_state_changed(
        self,
        state: Qt.ApplicationState,
    ) -> None:
        if state == Qt.ApplicationState.ApplicationActive:
            self.acknowledge()

    def _window_is_foreground(self) -> bool:
        return (
            self._application.applicationState()
            == Qt.ApplicationState.ApplicationActive
            and not self._window.isMinimized()
        )
