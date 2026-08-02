from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.processing_queue import (
    ProcessingQueue,
    ProcessingTask,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
)


_MAX_VISIBLE_TOASTS = 3
_TOAST_WIDTH = 340


class ToastStack(QWidget):
    geometry_changed = Signal()
    details_requested = Signal(str)

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToastStack")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(_TOAST_WIDTH)
        self._queue = queue
        self._known_statuses: dict[str, str] = {}
        self._cards: list[ToastCard] = []
        self._theme_mode = "white"

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.hide()
        self._queue.subscribe(self._on_tasks_changed)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for card in self._cards:
            card.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        for card in self._cards:
            card.apply_language()

    def dismiss_all(self) -> None:
        for card in tuple(self._cards):
            self._remove_card(card)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        next_statuses = {task.task_id: task.status for task in tasks}
        for task in reversed(tasks):
            previous = self._known_statuses.get(task.task_id)
            if previous == TASK_RUNNING and task.status in {TASK_COMPLETED, TASK_FAILED}:
                self._show_task_toast(task)
        self._known_statuses = next_statuses

    def _show_task_toast(self, task: ProcessingTask) -> None:
        card = ToastCard(task)
        card.set_theme_mode(self._theme_mode)
        card.apply_language()
        card.dismiss_requested.connect(lambda: self._remove_card(card))
        card.details_requested.connect(self.details_requested.emit)
        self._cards.insert(0, card)
        self._layout.insertWidget(0, card)
        while len(self._cards) > _MAX_VISIBLE_TOASTS:
            self._remove_card(self._cards[-1])
        self._sync_geometry()

    def _remove_card(self, card: "ToastCard") -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        self._sync_geometry()

    def _sync_geometry(self) -> None:
        if not self._cards:
            self.hide()
            self.setFixedHeight(0)
        else:
            card_heights = sum(card.sizeHint().height() for card in self._cards)
            height = card_heights + self._layout.spacing() * (len(self._cards) - 1)
            self.setFixedHeight(height)
            self.show()
            self.raise_()
        self.geometry_changed.emit()


class ToastCard(QFrame):
    dismiss_requested = Signal()
    details_requested = Signal(str)

    def __init__(self, task: ProcessingTask) -> None:
        super().__init__()
        self.setObjectName("ToastCard")
        self.setProperty("status", task.status)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._task_id = task.task_id
        self._task = task

        self.title_label = QLabel(task.title)
        self.title_label.setObjectName("ToastTitle")
        self.status_label = QLabel("Complete" if task.status == TASK_COMPLETED else "Failed")
        self.status_label.setObjectName("ToastStatus")
        self.status_label.setProperty("status", task.status)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label = QLabel(_toast_message(task))
        self.message_label.setObjectName("ToastMessage")
        self.message_label.setWordWrap(True)
        self.close_button = SvgIconButton("close", size=24)
        self.close_button.setObjectName("ToastCloseButton")
        set_translated_tooltip(self.close_button, "Dismiss")
        self.close_button.clicked.connect(self.dismiss_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status_label)
        header.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(5)
        layout.addLayout(header)
        layout.addWidget(self.message_label)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(6500 if task.status == TASK_FAILED else 4000)
        self._dismiss_timer.timeout.connect(self.dismiss_requested.emit)
        self._dismiss_timer.start()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.close_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_text(self.title_label, self._task.title)
        set_translated_text(
            self.status_label,
            "Complete" if self._task.status == TASK_COMPLETED else "Failed",
        )
        set_translated_text(self.message_label, _toast_message(self._task))
        apply_widget_language(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.details_requested.emit(self._task_id)
        super().mouseReleaseEvent(event)


def _toast_message(task: ProcessingTask) -> str:
    if task.status == TASK_FAILED:
        lines = [line.strip() for line in task.error.splitlines() if line.strip()]
        return lines[-1] if lines else "Processing failed"
    return task.detail or "Processing completed"
