from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from jang_app.qt_app.app_overlay import AppOverlayFrame
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.widgets import FeedbackButton, SvgIconButton, render_app_icon
from jang_app.services.i18n import tr
from jang_app.services.processing_queue import (
    ProcessingQueue,
    ProcessingTask,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
)
from jang_app.services.job_diagnostics import JobDiagnosticRecord


_DRAWER_WIDTH = 340
_MAX_VISIBLE_TASKS = 8
_QUEUE_BUTTON_COLLAPSED_WIDTH = 48
_QUEUE_BUTTON_ACTIVE_WIDTH = 184
_QUEUE_BUTTON_HEIGHT = 26


class ProcessingQueueButton(SvgIconButton):
    """Compact title-bar summary that opens the processing drawer on demand."""

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__("logs", size=30)
        self.lock_outer_size(_QUEUE_BUTTON_COLLAPSED_WIDTH, _QUEUE_BUTTON_HEIGHT)
        if parent is not None:
            self.setParent(parent)
        self.setObjectName("ProcessingQueueButton")
        self.setCheckable(True)
        self._queue = queue
        self._active_count = 0
        self._task_count = 0
        self._aggregate_progress = 0
        self._active_title_source = ""
        self._expanded = False
        self._queue.subscribe(self._on_tasks_changed)
        self.apply_language()

    def active_count(self) -> int:
        return self._active_count

    def task_count(self) -> int:
        return self._task_count

    def aggregate_progress(self) -> int:
        return self._aggregate_progress

    def active_title(self) -> str:
        return tr(self._active_title_source) if self._active_title_source else ""

    def apply_language(self) -> None:
        if self._task_count:
            action = (
                "Hide activity center ({count})"
                if self.isChecked()
                else "Show activity center ({count})"
            )
            set_translated_tooltip(self, action, count=self._task_count)
        else:
            action = "Hide activity center" if self.isChecked() else "Show activity center"
            set_translated_tooltip(self, action)
        self.setAccessibleName(tr("Activity Center"))
        self.setAccessibleDescription(self.active_title())
        self.update()

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

        count_divider_x = rect.right() - 24 if self._active_count else divider_x
        if self._active_count:
            painter.drawLine(
                round(count_divider_x),
                round(rect.top() + 7),
                round(count_divider_x),
                round(rect.bottom() - 7),
            )
            title_rect = QRectF(
                divider_x + 7,
                rect.top(),
                max(0.0, count_divider_x - divider_x - 12),
                rect.height(),
            )
            title_font = painter.font()
            title_font.setPixelSize(9)
            title_font.setBold(False)
            painter.setFont(title_font)
            painter.setPen(palette["icon"])
            title = painter.fontMetrics().elidedText(
                self.active_title(),
                Qt.TextElideMode.ElideRight,
                round(title_rect.width()),
            )
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )

        badge_text = "9+" if self._task_count > 9 else str(self._task_count)
        count_rect = QRectF(
            count_divider_x + 2,
            rect.top(),
            rect.right() - count_divider_x - 3,
            rect.height(),
        )
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
        self._active_title_source = active_tasks[0].title if active_tasks else ""
        self._set_expanded(bool(active_tasks))
        self.apply_language()
        self.update()

    def _set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        width = _QUEUE_BUTTON_ACTIVE_WIDTH if expanded else _QUEUE_BUTTON_COLLAPSED_WIDTH
        self.lock_outer_size(width, _QUEUE_BUTTON_HEIGHT)


class ProcessingQueuePanel(AppOverlayFrame):
    geometry_changed = Signal()
    diagnostics_requested = Signal()
    task_requested = Signal(str)
    close_requested = Signal()

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProcessingQueuePanel")
        self.setFixedWidth(_DRAWER_WIDTH)
        self._queue = queue
        self._active_rows: dict[str, ProcessingTaskRow] = {}
        self._recent_rows: dict[str, ProcessingTaskRow] = {}
        self._active_task_ids: tuple[str, ...] = ()
        self._recent_task_ids: tuple[str, ...] = ()
        self._queue_history_signature: tuple[tuple[str, str], ...] | None = None
        self._persisted_tasks: tuple[ProcessingTask, ...] = ()
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

        title = QLabel("Activity Center")
        title.setObjectName("ProcessingQueueTitle")
        self.activity_label = QLabel("Idle")
        self.activity_label.setObjectName("ProcessingQueueActivity")
        self.activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toggle_button = SvgIconButton("close", size=30)
        self.toggle_button.setObjectName("ProcessingQueueToggle")
        self.toggle_button.setToolTip("Hide activity center")
        self.toggle_button.clicked.connect(self.close_requested.emit)

        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.activity_label)
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
        task_layout = QVBoxLayout(self.task_container)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(7)

        self.active_label = QLabel("Running")
        self.active_label.setObjectName("ProcessingQueueSectionLabel")
        self.active_container = QWidget()
        self.active_layout = QVBoxLayout(self.active_container)
        self.active_layout.setContentsMargins(0, 0, 0, 0)
        self.active_layout.setSpacing(7)

        self.recent_label = QLabel("Recent")
        self.recent_label.setObjectName("ProcessingQueueSectionLabel")
        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(7)

        task_layout.addWidget(self.active_label)
        task_layout.addWidget(self.active_container)
        task_layout.addSpacing(6)
        task_layout.addWidget(self.recent_label)
        task_layout.addWidget(self.recent_container)
        task_layout.addStretch(1)
        self.scroll.setWidget(self.task_container)

        self.empty_label = QLabel("No recent processing")
        self.empty_label.setObjectName("ProcessingQueueEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.diagnostics_button = FeedbackButton("Open Environment & Management")
        self.diagnostics_button.setObjectName("ProcessingQueueClear")
        self.diagnostics_button.clicked.connect(self.diagnostics_requested.emit)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.diagnostics_button, 1)

        body_layout.addWidget(self.scroll, 1)
        body_layout.addWidget(self.empty_label, 1)
        body_layout.addLayout(footer)
        layout.addWidget(header)
        layout.addWidget(self.body, 1)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.toggle_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._on_tasks_changed(self._queue.tasks())
        set_translated_tooltip(self.toggle_button, "Hide activity center")

    def has_tasks(self) -> bool:
        return bool(self._queue.tasks() or self._persisted_tasks)

    def preferred_overlay_height(self) -> int:
        row_count = len(self._active_task_ids) + len(self._recent_task_ids)
        return min(460, 240 + min(row_count, 4) * 62)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        history_signature = tuple((task.task_id, task.status) for task in tasks)
        if history_signature != self._queue_history_signature:
            self._queue_history_signature = history_signature
            self._persisted_tasks = self._load_persisted_tasks()

        active_tasks = tuple(task for task in tasks if task.is_active)
        queued_ids = {task.task_id for task in tasks}
        recent_tasks = tuple(task for task in tasks if task.is_finished) + tuple(
            task for task in self._persisted_tasks if task.task_id not in queued_ids
        )
        recent_tasks = tuple(
            sorted(
                recent_tasks,
                key=lambda task: task.finished_at or task.created_at,
                reverse=True,
            )[:_MAX_VISIBLE_TASKS]
        )
        if active_tasks:
            set_translated_text(
                self.activity_label,
                "{count} active",
                count=len(active_tasks),
            )
            self.activity_label.setProperty("active", True)
        elif recent_tasks:
            set_translated_text(
                self.activity_label,
                "{count} recent",
                count=len(recent_tasks),
            )
            self.activity_label.setProperty("active", False)
        else:
            set_translated_text(self.activity_label, "Idle")
            self.activity_label.setProperty("active", False)
        self.activity_label.style().unpolish(self.activity_label)
        self.activity_label.style().polish(self.activity_label)
        self._sync_rows(
            self.active_layout,
            self._active_rows,
            active_tasks,
            active=True,
        )
        self._sync_rows(
            self.recent_layout,
            self._recent_rows,
            recent_tasks,
            active=False,
        )

        has_tasks = bool(active_tasks or recent_tasks)
        self.active_label.setVisible(bool(active_tasks))
        self.active_container.setVisible(bool(active_tasks))
        self.recent_label.setVisible(bool(recent_tasks))
        self.recent_container.setVisible(bool(recent_tasks))
        self.empty_label.setVisible(not has_tasks)
        self.scroll.setVisible(has_tasks)
        self.geometry_changed.emit()

    def refresh_history(self) -> None:
        self._persisted_tasks = self._load_persisted_tasks()
        self._on_tasks_changed(self._queue.tasks())

    def _load_persisted_tasks(self) -> tuple[ProcessingTask, ...]:
        diagnostics = self._queue.diagnostics
        if diagnostics is None:
            return ()
        return tuple(_task_from_record(record) for record in diagnostics.records(limit=20))

    def _sync_rows(
        self,
        layout: QVBoxLayout,
        rows: dict[str, "ProcessingTaskRow"],
        tasks: tuple[ProcessingTask, ...],
        *,
        active: bool,
    ) -> None:
        task_ids = tuple(task.task_id for task in tasks)
        previous_ids = self._active_task_ids if active else self._recent_task_ids
        if task_ids == previous_ids:
            for task in tasks:
                rows[task.task_id].update_task(task)
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rows.clear()
        for task in tasks:
            row = ProcessingTaskRow(task)
            row.activated.connect(self.task_requested.emit)
            rows[task.task_id] = row
            layout.addWidget(row)
        if active:
            self._active_task_ids = task_ids
        else:
            self._recent_task_ids = task_ids


class ProcessingTaskRow(QFrame):
    activated = Signal(str)

    def __init__(self, task: ProcessingTask) -> None:
        super().__init__()
        self.setObjectName("ProcessingTaskRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._task_id = task.task_id

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
        self._task_id = task.task_id
        set_translated_text(self.title_label, task.title)
        detail = _last_error_line(task.error) if task.status == TASK_FAILED else task.detail
        set_translated_text(self.detail_label, detail)
        self.detail_label.setToolTip(task.error or task.detail)
        self.setAccessibleName(tr(task.title))
        self.setAccessibleDescription(tr(detail) if detail else "")
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

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit(self._task_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self._task_id)
            event.accept()
            return
        super().keyPressEvent(event)


def _task_from_record(record: JobDiagnosticRecord) -> ProcessingTask:
    return ProcessingTask(
        task_id=record.task_id,
        title=record.title,
        detail=record.detail,
        status=record.status,
        progress=record.progress,
        created_at=record.started_at,
        finished_at=record.finished_at,
        error=record.error,
        diagnostic_path=record.path,
        diagnostic_code=record.diagnostic_code,
    )


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Processing failed"
