from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.widgets import FeedbackButton, SvgIconButton, render_app_icon
from jang_app.services.processing_queue import (
    ProcessingQueue,
    ProcessingTask,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
)


_DRAWER_WIDTH = 400
_MAX_VISIBLE_TASKS = 6


class ProcessingQueueButton(SvgIconButton):
    """Compact title-bar summary that opens the processing drawer on demand."""

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__("logs", size=30)
        self.lock_outer_size(48, 26)
        if parent is not None:
            self.setParent(parent)
        self.setObjectName("ProcessingQueueButton")
        self.setCheckable(True)
        self._queue = queue
        self._active_count = 0
        self._task_count = 0
        self._aggregate_progress = 0
        self._queue.subscribe(self._on_tasks_changed)
        self.apply_language()

    def active_count(self) -> int:
        return self._active_count

    def task_count(self) -> int:
        return self._task_count

    def aggregate_progress(self) -> int:
        return self._aggregate_progress

    def apply_language(self) -> None:
        action = "Hide processing queue ({count})" if self.isChecked() else "Show processing queue ({count})"
        set_translated_tooltip(self, action, count=self._task_count)

    def nextCheckState(self) -> None:  # noqa: N802
        super().nextCheckState()
        self.apply_language()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self._button_palette()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = palette.get("border", QColor(0, 0, 0, 0))
        painter.setPen(QPen(border, 1) if border.alpha() else Qt.PenStyle.NoPen)
        painter.setBrush(palette["background"])
        painter.drawRoundedRect(rect, 9, 9)

        icon_rect = QRectF(rect.left() + 7, rect.center().y() - 7, 14, 14)
        render_app_icon(painter, icon_rect, self._icon_key(), palette["icon"])

        divider_color = QColor(palette["icon"])
        divider_color.setAlpha(55)
        divider_x = rect.left() + 27
        painter.setPen(QPen(divider_color, 1))
        painter.drawLine(
            round(divider_x),
            round(rect.top() + 7),
            round(divider_x),
            round(rect.bottom() - 7),
        )

        badge_text = "9+" if self._task_count > 9 else str(self._task_count)
        count_rect = QRectF(divider_x + 2, rect.top(), rect.right() - divider_x - 3, rect.height())
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette["icon"])
        painter.drawText(count_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        if self._active_count:
            progress_width = max(
                3.0,
                (rect.width() - 8) * self._aggregate_progress / 100,
            )
            painter.setPen(
                QPen(
                    palette["icon"],
                    2.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(
                QPointF(rect.left() + 4, rect.bottom() - 2),
                QPointF(rect.left() + 4 + progress_width, rect.bottom() - 2),
            )
        self._draw_keyboard_focus(painter, rect, 9)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        active_tasks = tuple(task for task in tasks if task.is_active)
        self._active_count = len(active_tasks)
        self._task_count = len(tasks)
        self._aggregate_progress = (
            round(sum(task.progress for task in active_tasks) / len(active_tasks))
            if active_tasks
            else 0
        )
        self.setVisible(bool(tasks))
        self.apply_language()
        self.update()


class ProcessingQueuePanel(QFrame):
    geometry_changed = Signal()
    log_requested = Signal()
    close_requested = Signal()

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProcessingQueuePanel")
        self.setFixedWidth(_DRAWER_WIDTH)
        self._queue = queue
        self._rows: dict[str, ProcessingTaskRow] = {}
        self._visible_task_ids: tuple[str, ...] = ()
        self._theme_mode = "white"

        self._build_ui()
        self._queue.subscribe(self._on_tasks_changed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("ProcessingQueueHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 10, 8)
        header_layout.setSpacing(10)

        title = QLabel("Processing Queue")
        title.setObjectName("ProcessingQueueTitle")
        self.activity_label = QLabel("Idle")
        self.activity_label.setObjectName("ProcessingQueueActivity")
        self.activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log_button = SvgIconButton("logs", size=30)
        self.log_button.setObjectName("ProcessingQueueToggle")
        self.log_button.setToolTip("Open activity logs")
        self.log_button.clicked.connect(self.log_requested.emit)
        self.toggle_button = SvgIconButton("close", size=30)
        self.toggle_button.setObjectName("ProcessingQueueToggle")
        self.toggle_button.setToolTip("Hide processing queue")
        self.toggle_button.clicked.connect(self.close_requested.emit)

        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.activity_label)
        header_layout.addWidget(self.log_button)
        header_layout.addWidget(self.toggle_button)

        self.body = QWidget()
        self.body.setObjectName("ProcessingQueueBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(10, 6, 10, 10)
        body_layout.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ProcessingQueueScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_container = QWidget()
        self.task_container.setObjectName("ProcessingQueueTaskContainer")
        self.task_layout = QVBoxLayout(self.task_container)
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(7)
        self.scroll.setWidget(self.task_container)

        self.empty_label = QLabel("No recent processing")
        self.empty_label.setObjectName("ProcessingQueueEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.clear_button = FeedbackButton("Clear finished")
        self.clear_button.setObjectName("ProcessingQueueClear")
        self.clear_button.clicked.connect(self._queue.clear_finished)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        footer.addWidget(self.clear_button)

        body_layout.addWidget(self.scroll, 1)
        body_layout.addWidget(self.empty_label, 1)
        body_layout.addLayout(footer)
        layout.addWidget(header)
        layout.addWidget(self.body, 1)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.log_button.set_theme_mode(theme_mode)
        self.toggle_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._on_tasks_changed(self._queue.tasks())
        set_translated_tooltip(self.log_button, "Open activity logs")
        set_translated_tooltip(self.toggle_button, "Hide processing queue")

    def has_tasks(self) -> bool:
        return bool(self._queue.tasks())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        active_count = sum(task.is_active for task in tasks)
        if active_count:
            set_translated_text(self.activity_label, "{count} active", count=active_count)
            self.activity_label.setProperty("active", True)
        elif tasks:
            set_translated_text(self.activity_label, "{count} recent", count=len(tasks))
            self.activity_label.setProperty("active", False)
        else:
            set_translated_text(self.activity_label, "Idle")
            self.activity_label.setProperty("active", False)
        self.activity_label.style().unpolish(self.activity_label)
        self.activity_label.style().polish(self.activity_label)

        visible_tasks = tasks[:_MAX_VISIBLE_TASKS]
        visible_ids = tuple(task.task_id for task in visible_tasks)
        if visible_ids != self._visible_task_ids:
            self._rebuild_rows(visible_tasks)
        else:
            for task in visible_tasks:
                self._rows[task.task_id].update_task(task)

        self.empty_label.setVisible(not visible_tasks)
        self.scroll.setVisible(bool(visible_tasks))
        self.clear_button.setVisible(any(task.is_finished for task in tasks))
        self.geometry_changed.emit()

    def _rebuild_rows(self, tasks: tuple[ProcessingTask, ...]) -> None:
        while self.task_layout.count():
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        for task in tasks:
            row = ProcessingTaskRow(task)
            self._rows[task.task_id] = row
            self.task_layout.addWidget(row)
        self.task_layout.addStretch(1)
        self._visible_task_ids = tuple(task.task_id for task in tasks)

class ProcessingTaskRow(QFrame):
    def __init__(self, task: ProcessingTask) -> None:
        super().__init__()
        self.setObjectName("ProcessingTaskRow")

        self.title_label = OverflowTextLabel(object_name="ProcessingTaskTitle", fixed_height=18)
        self.detail_label = OverflowTextLabel(object_name="ProcessingTaskDetail", fixed_height=16)
        self.status_label = QLabel()
        self.status_label.setObjectName("ProcessingTaskStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ProcessingTaskProgress")
        self.progress_bar.setRange(0, 100)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.status_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(5)
        layout.addLayout(title_row)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.progress_bar)
        self.update_task(task)

    def update_task(self, task: ProcessingTask) -> None:
        set_translated_text(self.title_label, task.title)
        detail = _last_error_line(task.error) if task.status == TASK_FAILED else task.detail
        set_translated_text(self.detail_label, detail)
        self.detail_label.setToolTip(task.error or task.detail)
        self.detail_label.setVisible(bool(detail))
        self.progress_bar.setValue(task.progress)
        self.progress_bar.setVisible(task.is_active)

        if task.status == TASK_COMPLETED:
            status_text = "Complete"
        elif task.status == TASK_FAILED:
            status_text = "Failed"
        elif task.status == TASK_CANCELLED:
            status_text = "Stopped"
        else:
            status_text = f"{task.progress}%"
        set_translated_text(self.status_label, status_text)
        self.status_label.setProperty("status", task.status)
        self.setProperty("status", task.status)
        for widget in (self, self.status_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Processing failed"
