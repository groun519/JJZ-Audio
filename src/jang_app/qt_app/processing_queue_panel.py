from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget

from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.processing_queue import ProcessingQueue, ProcessingTask, TASK_COMPLETED, TASK_FAILED


_COLLAPSED_HEIGHT = 46
_COLLAPSED_WIDTH = 300
_EXPANDED_WIDTH = 380
_MAX_VISIBLE_TASKS = 6


class ProcessingQueuePanel(QFrame):
    geometry_changed = Signal()
    log_requested = Signal()

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProcessingQueuePanel")
        self.setFixedWidth(_COLLAPSED_WIDTH)
        self._queue = queue
        self._rows: dict[str, ProcessingTaskRow] = {}
        self._visible_task_ids: tuple[str, ...] = ()
        self._is_expanded = False
        self._active_count = 0
        self._theme_mode = "white"
        self._idle_collapse_timer = QTimer(self)
        self._idle_collapse_timer.setSingleShot(True)
        self._idle_collapse_timer.setInterval(800)
        self._idle_collapse_timer.timeout.connect(self._collapse_if_idle)

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
        self.toggle_button = SvgIconButton("chevron_up", size=30)
        self.toggle_button.setObjectName("ProcessingQueueToggle")
        self.toggle_button.setToolTip("Show processing queue")
        self.toggle_button.clicked.connect(self.toggle_expanded)

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

        self.clear_button = QPushButton("Clear finished")
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
        self._apply_expanded_state()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.log_button.set_theme_mode(theme_mode)
        self.toggle_button.set_theme_mode(theme_mode)

    def toggle_expanded(self) -> None:
        self._idle_collapse_timer.stop()
        self.set_expanded(not self._is_expanded)

    def set_expanded(self, is_expanded: bool) -> None:
        if self._is_expanded == is_expanded:
            return
        self._is_expanded = is_expanded
        self._apply_expanded_state()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        active_count = sum(task.is_active for task in tasks)
        if self._active_count == 0 and active_count > 0:
            self._idle_collapse_timer.stop()
            self.set_expanded(True)
        elif self._active_count > 0 and active_count == 0:
            self._idle_collapse_timer.start()
        self._active_count = active_count

        if active_count:
            self.activity_label.setText(f"{active_count} active")
            self.activity_label.setProperty("active", True)
        elif tasks:
            self.activity_label.setText(f"{len(tasks)} recent")
            self.activity_label.setProperty("active", False)
        else:
            self.activity_label.setText("Idle")
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
        if self._is_expanded:
            self._resize_expanded_panel()

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

    def _apply_expanded_state(self) -> None:
        self.body.setVisible(self._is_expanded)
        self.toggle_button.set_icon_name("chevron_down" if self._is_expanded else "chevron_up")
        self.toggle_button.setToolTip("Hide processing queue" if self._is_expanded else "Show processing queue")
        if self._is_expanded:
            self.setFixedWidth(_EXPANDED_WIDTH)
            self._resize_expanded_panel()
        else:
            self.setFixedWidth(_COLLAPSED_WIDTH)
            self.setFixedHeight(_COLLAPSED_HEIGHT)
            self.geometry_changed.emit()

    def _resize_expanded_panel(self) -> None:
        row_count = max(1, len(self._visible_task_ids))
        body_height = min(264, 52 + row_count * 72)
        self.setFixedHeight(_COLLAPSED_HEIGHT + body_height)
        self.geometry_changed.emit()

    def _collapse_if_idle(self) -> None:
        if self._active_count == 0:
            self.set_expanded(False)


class ProcessingTaskRow(QFrame):
    def __init__(self, task: ProcessingTask) -> None:
        super().__init__()
        self.setObjectName("ProcessingTaskRow")

        self.title_label = QLabel()
        self.title_label.setObjectName("ProcessingTaskTitle")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("ProcessingTaskDetail")
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
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
        self.title_label.setText(task.title)
        detail = _last_error_line(task.error) if task.status == TASK_FAILED else task.detail
        self.detail_label.setText(detail)
        self.detail_label.setToolTip(task.error or task.detail)
        self.detail_label.setVisible(bool(detail))
        self.progress_bar.setValue(task.progress)
        self.progress_bar.setVisible(task.is_active)

        status_text = "Complete" if task.status == TASK_COMPLETED else "Failed" if task.status == TASK_FAILED else f"{task.progress}%"
        self.status_label.setText(status_text)
        self.status_label.setProperty("status", task.status)
        self.setProperty("status", task.status)
        for widget in (self, self.status_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Processing failed"
