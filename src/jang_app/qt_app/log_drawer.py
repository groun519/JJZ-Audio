from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import LOG_FILE
from jang_app.qt_app.app_overlay import AppOverlayFrame
from jang_app.qt_app.localization import apply_widget_language
from jang_app.qt_app.widgets import FeedbackButton, SvgIconButton, attach_list_item_widget
from jang_app.services.i18n import tr
from jang_app.services.log_reader import read_log_tail
from jang_app.services.processing_queue import (
    ProcessingQueue,
    ProcessingTask,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
)


class LogDrawer(AppOverlayFrame):
    close_requested = Signal()
    queue_requested = Signal()
    open_location_requested = Signal(object)

    def __init__(self, queue: ProcessingQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogDrawer")
        self.setFixedWidth(520)
        self._queue = queue
        self._tasks: tuple[ProcessingTask, ...] = ()
        self._tasks_by_id: dict[str, ProcessingTask] = {}
        self._activity_rows: dict[str, ActivityTaskRow] = {}
        self._theme_mode = "white"
        self._pending_task_id: str | None = None

        self._build_ui()
        self.hide()
        self._queue.subscribe(self._on_tasks_changed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Activity & Logs")
        title.setObjectName("LogDrawerTitle")
        self.queue_button = SvgIconButton("arrow_left", size=30)
        self.queue_button.setObjectName("LogDrawerIconButton")
        self.queue_button.setToolTip("Back to processing queue")
        self.queue_button.clicked.connect(self.queue_requested.emit)
        self.open_button = SvgIconButton("folder", size=30)
        self.open_button.setObjectName("LogDrawerIconButton")
        self.open_button.setToolTip("Open log location")
        self.open_button.clicked.connect(lambda: self.open_location_requested.emit(LOG_FILE))
        self.refresh_button = SvgIconButton("refresh", size=30)
        self.refresh_button.setObjectName("LogDrawerIconButton")
        self.refresh_button.setToolTip("Refresh logs")
        self.refresh_button.clicked.connect(self.refresh_content)
        self.close_button = SvgIconButton("close", size=30)
        self.close_button.setObjectName("LogDrawerIconButton")
        self.close_button.setToolTip("Close logs")
        self.close_button.clicked.connect(self.close_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.queue_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.open_button)
        header.addWidget(self.refresh_button)
        header.addWidget(self.close_button)

        segment = QFrame()
        segment.setObjectName("SegmentedControl")
        segment_layout = QHBoxLayout(segment)
        segment_layout.setContentsMargins(4, 4, 4, 4)
        segment_layout.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for index, label in enumerate(("Activity", "Application Log")):
            button = FeedbackButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.tab_group.addButton(button, index)
            segment_layout.addWidget(button, 1)
        self.tab_group.idClicked.connect(self._show_tab)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._build_activity_page())
        self.page_stack.addWidget(self._build_application_log_page())

        layout.addLayout(header)
        layout.addWidget(segment)
        layout.addWidget(self.page_stack, 1)

    def _build_activity_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("LogDrawerPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.activity_list = QListWidget()
        self.activity_list.setObjectName("LogActivityList")
        self.activity_list.setMaximumHeight(230)
        self.activity_list.currentItemChanged.connect(self._on_activity_selected)

        detail_title = QLabel("Details")
        detail_title.setObjectName("CardTitle")
        self.activity_detail = QPlainTextEdit()
        self.activity_detail.setObjectName("LogDetailText")
        self.activity_detail.setReadOnly(True)
        self.activity_detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.copy_diagnostics_button = FeedbackButton("Copy diagnostics")
        self.copy_diagnostics_button.setObjectName("LogDrawerActionButton")
        self.copy_diagnostics_button.clicked.connect(self._copy_selected_diagnostics)
        self.diagnostic_package_button = FeedbackButton("Diagnostic file")
        self.diagnostic_package_button.setObjectName("LogDrawerActionButton")
        self.diagnostic_package_button.clicked.connect(
            self._open_selected_diagnostic_package
        )
        self.open_task_log_button = SvgIconButton("folder", size=32)
        self.open_task_log_button.setObjectName("LogDrawerTaskFolderButton")
        self.open_task_log_button.setToolTip("Open task log folder")
        self.open_task_log_button.clicked.connect(self._open_selected_task_log)
        self.diagnostic_status_label = QLabel("")
        self.diagnostic_status_label.setObjectName("LogDrawerDiagnosticStatus")

        diagnostic_actions = QHBoxLayout()
        diagnostic_actions.setContentsMargins(0, 0, 0, 0)
        diagnostic_actions.setSpacing(8)
        diagnostic_actions.addWidget(self.diagnostic_status_label, 1)
        diagnostic_actions.addWidget(self.open_task_log_button)
        diagnostic_actions.addWidget(self.diagnostic_package_button)
        diagnostic_actions.addWidget(self.copy_diagnostics_button)

        layout.addWidget(self.activity_list)
        layout.addWidget(detail_title)
        layout.addWidget(self.activity_detail, 1)
        layout.addLayout(diagnostic_actions)
        self._set_diagnostic_actions(None)
        return page

    def _build_application_log_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("LogDrawerPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.application_log = QPlainTextEdit()
        self.application_log.setObjectName("ApplicationLogText")
        self.application_log.setReadOnly(True)
        self.application_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_path_label = QLabel(str(LOG_FILE))
        self.log_path_label.setObjectName("LogPathLabel")
        self.log_path_label.setToolTip(str(LOG_FILE))

        layout.addWidget(self.application_log, 1)
        layout.addWidget(self.log_path_label)
        return page

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for button in (
            self.queue_button,
            self.open_button,
            self.refresh_button,
            self.close_button,
            self.open_task_log_button,
        ):
            button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        selected_task_id = self._selected_task_id()
        apply_widget_language(self)
        self._refresh_activity_list(selected_task_id)
        if not self._tasks:
            self.activity_detail.setPlainText(tr("No processing activity yet."))

    def refresh_content(self) -> None:
        self._refresh_activity_list(self._selected_task_id() or self._pending_task_id)
        log_text = read_log_tail()
        self.application_log.setPlainText(log_text or tr("No application log entries yet."))
        scroll_bar = self.application_log.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def select_task(self, task_id: str) -> None:
        self._pending_task_id = task_id
        self.page_stack.setCurrentIndex(0)
        button = self.tab_group.button(0)
        if button is not None:
            button.setChecked(True)
        self._select_task_item(task_id)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_tasks_changed)
        super().closeEvent(event)

    def _on_tasks_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        self._tasks = tasks
        self._tasks_by_id = {task.task_id: task for task in tasks}
        if self.isVisible():
            self._refresh_activity_list(self._selected_task_id())

    def _refresh_activity_list(self, selected_task_id: str | None = None) -> None:
        self.activity_list.blockSignals(True)
        self.activity_list.clear()
        self._activity_rows.clear()
        for task in self._tasks:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            row = ActivityTaskRow(task, self.activity_list.viewport())
            row.activated.connect(self.select_task)
            attach_list_item_widget(self.activity_list, item, row)
            self._activity_rows[task.task_id] = row
        self.activity_list.blockSignals(False)

        target_id = selected_task_id or self._pending_task_id
        if target_id and self._select_task_item(target_id):
            self._pending_task_id = None
            return
        if self.activity_list.count():
            self.activity_list.setCurrentRow(0)
        else:
            self.activity_detail.setPlainText(tr("No processing activity yet."))

    def _select_task_item(self, task_id: str) -> bool:
        for index in range(self.activity_list.count()):
            item = self.activity_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == task_id:
                self.activity_list.setCurrentItem(item)
                self._show_task_detail(self._tasks_by_id.get(task_id))
                return True
        return False

    def _selected_task_id(self) -> str | None:
        item = self.activity_list.currentItem()
        task_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return task_id if isinstance(task_id, str) else None

    def _on_activity_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        task_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        for row_id, row in self._activity_rows.items():
            row.set_selected(row_id == task_id)
        self._show_task_detail(self._tasks_by_id.get(task_id) if isinstance(task_id, str) else None)

    def _show_task_detail(self, task: ProcessingTask | None) -> None:
        self.activity_detail.setPlainText(_format_task_detail(task) if task is not None else tr("No task selected."))
        self._set_diagnostic_actions(task)

    def _set_diagnostic_actions(self, task: ProcessingTask | None) -> None:
        available = (
            task is not None
            and task.diagnostic_path is not None
            and self._queue.diagnostics is not None
        )
        self.copy_diagnostics_button.setEnabled(available)
        self.diagnostic_package_button.setEnabled(available)
        self.open_task_log_button.setEnabled(available)
        self.diagnostic_status_label.clear()

    def _copy_selected_diagnostics(self) -> None:
        task_id = self._selected_task_id()
        diagnostics = self._queue.diagnostics
        if not task_id or diagnostics is None:
            return
        QApplication.clipboard().setText(diagnostics.build_report(task_id))
        self.diagnostic_status_label.setText(tr("Copied"))
        QTimer.singleShot(1600, self.diagnostic_status_label.clear)

    def _open_selected_task_log(self) -> None:
        task = self._tasks_by_id.get(self._selected_task_id() or "")
        if task is not None and task.diagnostic_path is not None:
            self.open_location_requested.emit(task.diagnostic_path)

    def _open_selected_diagnostic_package(self) -> None:
        task_id = self._selected_task_id()
        diagnostics = self._queue.diagnostics
        if not task_id or diagnostics is None:
            return
        archive = diagnostics.build_archive(task_id)
        if archive is None:
            self.diagnostic_status_label.setText(tr("Diagnostic file unavailable"))
            return
        self.diagnostic_status_label.setText(tr("Diagnostic file ready"))
        self.open_location_requested.emit(archive)

    def _show_tab(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        if index == 1:
            self.refresh_content()


class ActivityTaskRow(QWidget):
    activated = Signal(str)

    def __init__(
        self,
        task: ProcessingTask,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityTaskRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._task_id = task.task_id

        title = QLabel(tr(task.title))
        title.setObjectName("ActivityTaskTitle")
        detail = QLabel(tr(task.detail) if task.detail else _task_time(task))
        detail.setObjectName("ActivityTaskMeta")
        status = QLabel(_task_status_label(task))
        status.setObjectName("ActivityTaskStatus")
        status.setProperty("status", task.status)
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(title)
        text_layout.addWidget(detail)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addLayout(text_layout, 1)
        layout.addWidget(status)

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self._task_id)
        super().mouseReleaseEvent(event)


def _task_status_label(task: ProcessingTask) -> str:
    if task.status == TASK_COMPLETED:
        return tr("Complete")
    if task.status == TASK_FAILED:
        return tr("Failed")
    if task.status == TASK_CANCELLED:
        return tr("Stopped")
    return f"{task.progress}%"


def _task_time(task: ProcessingTask) -> str:
    return task.created_at.astimezone().strftime("%H:%M:%S")


def _format_task_detail(task: ProcessingTask) -> str:
    lines = [
        tr(task.title),
        f"{tr('Status')}: {_task_status_label(task)}",
        f"{tr('Started')}: {task.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if task.finished_at is not None:
        lines.append(f"{tr('Finished')}: {task.finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"{tr('Task ID')}: {task.task_id}")
    if task.diagnostic_code:
        lines.append(f"{tr('Diagnostic ID')}: {task.diagnostic_code}")
    if task.detail:
        lines.extend(("", tr(task.detail)))
    if task.error:
        lines.extend(("", tr("Error"), task.error))
    return "\n".join(lines)
