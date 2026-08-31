from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import APP_ICON_PATH, APP_PATHS, LOG_FILE
from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.confirmation_dialog import ConfirmationDialog
from jang_app.qt_app.environment_management_panels import (
    EnvironmentNavigationButton,
    PcEnvironmentPanel,
    RvcEnvironmentPanel,
    StorageManagementPanel,
)
from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import (
    FeedbackButton,
    SvgIconButton,
    attach_list_item_widget,
)
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.command import terminate_all_commands
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import JobDiagnosticRecord, JobDiagnostics
from jang_app.services.log_reader import read_log_tail
from jang_app.services.processing_queue import ProcessingQueue, ProcessingTask
from jang_app.services.rvc_environment_status import (
    RvcEnvironmentSnapshot,
    collect_rvc_environment_status,
)
from jang_app.services.storage_management import (
    StorageCleanupPlan,
    StorageCleanupReport,
    StorageInventory,
    build_safe_cleanup_plan,
    execute_cleanup,
    scan_storage,
)
from jang_app.services.support_diagnostics import build_support_archive
from jang_app.services.system_environment import (
    PcEnvironmentSnapshot,
    collect_pc_environment,
)


_PAGE_JOBS = 0
_PAGE_APP_LOG = 1
_PAGE_PC = 2
_PAGE_RVC = 3
_PAGE_STORAGE = 4
_TAB_JOBS = _PAGE_JOBS
_TAB_APP_LOG = _PAGE_APP_LOG
_DETAIL_SUMMARY = 0
_DETAIL_LOG = 1
_DETAIL_ENVIRONMENT = 2
_HISTORY_ROW_HEIGHT = 64
_HISTORY_ITEM_HEIGHT = 70
_COMPACT_LAYOUT_WIDTH = 1180


@dataclass(frozen=True)
class DiagnosticTask:
    task_id: str
    title: str
    detail: str
    status: str
    progress: int
    started_at: datetime
    finished_at: datetime | None
    diagnostic_code: str
    diagnostic_summary: str
    error: str
    app_version: str
    path: Path | None
    environment: dict[str, object]


class DiagnosticsPage(QFrame):
    back_requested = Signal()
    open_location_requested = Signal(object)
    system_setup_requested = Signal()

    def __init__(
        self,
        queue: ProcessingQueue,
        diagnostics: JobDiagnostics,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DiagnosticsPage")
        self._queue = queue
        self._diagnostics = diagnostics
        self._tasks: tuple[DiagnosticTask, ...] = ()
        self._tasks_by_id: dict[str, DiagnosticTask] = {}
        self._persisted_tasks: tuple[DiagnosticTask, ...] = ()
        self._queue_signature: tuple[tuple[str, str], ...] | None = None
        self._pending_task_id = ""
        self._theme_mode = "white"
        self._support_worker: TaskWorker | None = None
        self._pc_worker: TaskWorker | None = None
        self._rvc_worker: TaskWorker | None = None
        self._storage_worker: TaskWorker | None = None
        self._cleanup_worker: TaskWorker | None = None
        self._pc_snapshot: PcEnvironmentSnapshot | None = None
        self._rvc_snapshot: RvcEnvironmentSnapshot | None = None
        self._storage_inventory: StorageInventory | None = None
        self._cleanup_plan = StorageCleanupPlan(())
        self._raw_application_log = ""
        self._navigation_compact: bool | None = None

        self._log_refresh_timer = QTimer(self)
        self._log_refresh_timer.setInterval(1200)
        self._log_refresh_timer.timeout.connect(self._refresh_visible_log)

        self._build_ui()
        self._queue.subscribe(self._on_queue_changed)
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.shutdown)
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("DiagnosticsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 14, 12)
        header_layout.setSpacing(10)

        self.back_button = SvgIconButton("arrow_left", size=34)
        self.back_button.setObjectName("DiagnosticsIconButton")
        self.back_button.setToolTip("Back")
        self.back_button.clicked.connect(self.back_requested.emit)
        self.title_label = QLabel("Environment & Management")
        self.title_label.setObjectName("DiagnosticsTitle")
        self.description = QLabel(
            "Review job history, app logs, runtime environment, and storage."
        )
        self.description.setObjectName("DiagnosticsDescription")
        self.description.setWordWrap(True)
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(3)
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.description)

        self.open_logs_button = SvgIconButton("folder", size=34)
        self.open_logs_button.setObjectName("DiagnosticsIconButton")
        set_translated_tooltip(self.open_logs_button, "Open Log Folder")
        self.open_logs_button.setAccessibleName(tr("Open Log Folder"))
        self.open_logs_button.clicked.connect(
            lambda: self.open_location_requested.emit(APP_PATHS.log_dir)
        )
        self.support_button = FeedbackButton("Create Diagnostics ZIP")
        self.support_button.setObjectName("DiagnosticsPrimaryButton")
        self.support_button.clicked.connect(self._create_support_archive)
        self.refresh_button = SvgIconButton("refresh", size=34)
        self.refresh_button.setObjectName("DiagnosticsIconButton")
        set_translated_tooltip(self.refresh_button, "Refresh")
        self.refresh_button.setAccessibleName(tr("Refresh"))
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))

        header_layout.addWidget(self.back_button)
        header_layout.addLayout(title_layout, 1)
        header_layout.addWidget(self.open_logs_button)
        header_layout.addWidget(self.support_button)
        header_layout.addWidget(self.refresh_button)

        body = QFrame()
        body.setObjectName("EnvironmentManagementBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self.navigation_frame = QFrame()
        self.navigation_frame.setObjectName("DiagnosticsNavigation")
        navigation_layout = QVBoxLayout(self.navigation_frame)
        navigation_layout.setContentsMargins(6, 6, 6, 6)
        navigation_layout.setSpacing(4)
        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        navigation_items = (
            ("Job History", "list", "Recent processing history"),
            ("Application Log", "logs", "Live application log"),
            ("PC Environment", "management", "Hardware and memory"),
            ("RVC Environment", "model", "Runtime and acceleration"),
            ("Storage Management", "database", "Usage and safe cleanup"),
        )
        self.navigation_buttons: list[EnvironmentNavigationButton] = []
        for index, (label, icon, summary) in enumerate(navigation_items):
            button = EnvironmentNavigationButton(label, icon)
            button.set_summary(summary)
            button.setChecked(index == _PAGE_JOBS)
            self.navigation_group.addButton(button, index)
            self.navigation_buttons.append(button)
            navigation_layout.addWidget(button)
        navigation_layout.addStretch(1)
        self.navigation_group.idClicked.connect(self._show_page)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("EnvironmentPageStack")
        self.page_stack.addWidget(self._build_jobs_page())
        self.page_stack.addWidget(self._build_app_log_page())
        self.pc_panel = PcEnvironmentPanel()
        self.rvc_panel = RvcEnvironmentPanel()
        self.storage_panel = StorageManagementPanel()
        self.page_stack.addWidget(self.pc_panel)
        self.page_stack.addWidget(self.rvc_panel)
        self.page_stack.addWidget(self.storage_panel)
        self.pc_panel.refresh_requested.connect(
            lambda: self._refresh_pc_environment(force=True)
        )
        self.rvc_panel.detailed_check_requested.connect(
            lambda: self._refresh_rvc_environment(deep=True)
        )
        self.rvc_panel.repair_requested.connect(self.system_setup_requested.emit)
        self.rvc_panel.open_location_requested.connect(
            self.open_location_requested.emit
        )
        self.storage_panel.scan_requested.connect(
            lambda: self._refresh_storage(force=True)
        )
        self.storage_panel.cleanup_requested.connect(self._confirm_cleanup)
        self.storage_panel.locations_requested.connect(
            self.system_setup_requested.emit
        )
        self.storage_panel.open_location_requested.connect(
            self.open_location_requested.emit
        )
        self.storage_panel.set_locations(self._storage_locations())
        self.run_system_diagnostics_button = self.rvc_panel.repair_button

        body_layout.addWidget(self.navigation_frame)
        body_layout.addWidget(self.page_stack, 1)

        layout.addWidget(header)
        layout.addWidget(body, 1)

    def _build_jobs_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("DiagnosticsJobsPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.jobs_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.jobs_splitter.setObjectName("DiagnosticsSplitter")
        self.jobs_splitter.setChildrenCollapsible(False)
        self.history_panel = self._build_history_panel()
        self.detail_panel = self._build_detail_panel()
        self.jobs_splitter.addWidget(self.history_panel)
        self.jobs_splitter.addWidget(self.detail_panel)
        self.jobs_splitter.setSizes((320, 760))
        self.jobs_splitter.setStretchFactor(0, 0)
        self.jobs_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.jobs_splitter)
        return page

    def _build_history_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DiagnosticsHistoryPanel")
        panel.setMinimumWidth(250)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        heading_row = QHBoxLayout()
        heading = QLabel("Job History")
        heading.setObjectName("DiagnosticsSectionTitle")
        self.history_count_label = QLabel("")
        self.history_count_label.setObjectName("DiagnosticsMutedText")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.history_count_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(7)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("DiagnosticsSearch")
        self.search_edit.setPlaceholderText("Search jobs")
        self.search_edit.textChanged.connect(
            lambda _text: self._refresh_history_list()
        )
        self.status_combo = QComboBox()
        self.status_combo.setObjectName("DiagnosticsFilter")
        for label, status in (
            ("All Statuses", ""),
            ("Running", "running"),
            ("Completed", "completed"),
            ("Failed", "failed"),
            ("Stopped", "cancelled"),
        ):
            self.status_combo.addItem(tr(label), status)
        self.status_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_history_list()
        )
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.status_combo)

        self.history_list = QListWidget()
        self.history_list.setObjectName("DiagnosticsHistoryList")
        self.history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        self.empty_history_label = QLabel("No diagnostic history yet.")
        self.empty_history_label.setObjectName("DiagnosticsEmpty")
        self.empty_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(heading_row)
        layout.addLayout(filter_row)
        layout.addWidget(self.history_list, 1)
        layout.addWidget(self.empty_history_label, 1)
        return panel

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DiagnosticsDetailPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(3)
        self.detail_title = QLabel("Select a job")
        self.detail_title.setObjectName("DiagnosticsDetailTitle")
        self.detail_subtitle = QLabel("")
        self.detail_subtitle.setObjectName("DiagnosticsMutedText")
        self.detail_subtitle.setWordWrap(True)
        title_layout.addWidget(self.detail_title)
        title_layout.addWidget(self.detail_subtitle)
        self.detail_status = QLabel("")
        self.detail_status.setObjectName("DiagnosticsStatusPill")
        self.detail_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addLayout(title_layout, 1)
        title_row.addWidget(self.detail_status)

        detail_tabs = QFrame()
        detail_tabs.setObjectName("DiagnosticsDetailTabs")
        detail_tab_layout = QHBoxLayout(detail_tabs)
        detail_tab_layout.setContentsMargins(0, 0, 0, 0)
        detail_tab_layout.setSpacing(4)
        self.detail_tab_group = QButtonGroup(self)
        self.detail_tab_group.setExclusive(True)
        for index, label in enumerate(("Summary", "Job Log", "Environment")):
            button = FeedbackButton(label)
            button.setObjectName("DiagnosticsDetailTab")
            button.setCheckable(True)
            button.setChecked(index == _DETAIL_SUMMARY)
            self.detail_tab_group.addButton(button, index)
            detail_tab_layout.addWidget(button)
        detail_tab_layout.addStretch(1)
        self.detail_tab_group.idClicked.connect(self._show_detail_tab)

        self.detail_stack = QStackedWidget()
        self.detail_stack.setObjectName("DiagnosticsDetailStack")
        self.summary_text = self._read_only_text("DiagnosticsSummaryText", wrap=True)
        self.command_log_text = self._read_only_text("DiagnosticsLogText")
        self.environment_text = self._read_only_text("DiagnosticsSummaryText", wrap=True)
        self.detail_stack.addWidget(self.summary_text)
        self.detail_stack.addWidget(self.command_log_text)
        self.detail_stack.addWidget(self.environment_text)

        self.action_status = QLabel("")
        self.action_status.setObjectName("DiagnosticsActionStatus")
        self.open_task_folder_button = FeedbackButton("Open Job Folder")
        self.open_task_folder_button.setObjectName("DiagnosticsActionButton")
        self.open_task_folder_button.clicked.connect(self._open_selected_folder)
        self.copy_button = FeedbackButton("Copy Diagnostics")
        self.copy_button.setObjectName("DiagnosticsActionButton")
        self.copy_button.clicked.connect(self._copy_selected_report)
        self.package_button = FeedbackButton("Create Diagnostic ZIP")
        self.package_button.setObjectName("DiagnosticsPrimaryButton")
        self.package_button.clicked.connect(self._create_selected_archive)
        actions = QHBoxLayout()
        actions.addWidget(self.action_status, 1)
        actions.addWidget(self.open_task_folder_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.package_button)

        layout.addLayout(title_row)
        layout.addWidget(detail_tabs)
        layout.addWidget(self.detail_stack, 1)
        layout.addLayout(actions)
        self._set_detail_actions_enabled(False)
        return panel

    def _build_app_log_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("DiagnosticsLogPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)

        heading_row = QHBoxLayout()
        heading = QLabel("Application Log")
        heading.setObjectName("DiagnosticsSectionTitle")
        description = QLabel(
            "Includes app errors that happened before a processing job was created."
        )
        description.setObjectName("DiagnosticsMutedText")
        heading_layout = QVBoxLayout()
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(3)
        heading_layout.addWidget(heading)
        heading_layout.addWidget(description)
        self.copy_app_log_button = FeedbackButton("Copy Log")
        self.copy_app_log_button.setObjectName("DiagnosticsActionButton")
        self.copy_app_log_button.clicked.connect(self._copy_app_log)
        heading_row.addLayout(heading_layout, 1)
        heading_row.addWidget(self.copy_app_log_button)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.log_search_edit = QLineEdit()
        self.log_search_edit.setObjectName("DiagnosticsSearch")
        self.log_search_edit.setPlaceholderText("Search log")
        self.log_search_edit.textChanged.connect(self._apply_app_log_filter)
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.setObjectName("DiagnosticsFilter")
        for label, value in (
            ("All Levels", ""),
            ("Errors", "error"),
            ("Warnings", "warning"),
        ):
            self.log_filter_combo.addItem(tr(label), value)
        self.log_filter_combo.currentIndexChanged.connect(
            self._apply_app_log_filter
        )
        self.log_auto_scroll_button = FeedbackButton("Auto Scroll")
        self.log_auto_scroll_button.setObjectName("DiagnosticsToggleButton")
        self.log_auto_scroll_button.setCheckable(True)
        self.log_auto_scroll_button.setChecked(True)
        filter_row.addWidget(self.log_search_edit, 1)
        filter_row.addWidget(self.log_filter_combo)
        filter_row.addWidget(self.log_auto_scroll_button)

        self.application_log = self._read_only_text("DiagnosticsLogText")
        self.log_path_label = QLabel(str(LOG_FILE))
        self.log_path_label.setObjectName("DiagnosticsMutedText")
        self.log_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addLayout(heading_row)
        layout.addLayout(filter_row)
        layout.addWidget(self.application_log, 1)
        layout.addWidget(self.log_path_label)
        return page

    @staticmethod
    def _read_only_text(object_name: str, *, wrap: bool = False) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setObjectName(object_name)
        editor.setReadOnly(True)
        if not wrap:
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return editor

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.back_button.set_theme_mode(theme_mode)
        self.open_logs_button.set_theme_mode(theme_mode)
        self.refresh_button.set_theme_mode(theme_mode)
        for button in self.navigation_buttons:
            button.set_theme_mode(theme_mode)
        self.pc_panel.set_theme_mode(theme_mode)
        self.rvc_panel.set_theme_mode(theme_mode)
        self.storage_panel.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        selected_id = self.selected_task_id()
        apply_widget_language(self)
        self.open_logs_button.setAccessibleName(tr("Open Log Folder"))
        self.refresh_button.setAccessibleName(tr("Refresh"))
        for index, label in enumerate(
            ("All Statuses", "Running", "Completed", "Failed", "Stopped")
        ):
            self.status_combo.setItemText(index, tr(label))
        for index, label in enumerate(("All Levels", "Errors", "Warnings")):
            self.log_filter_combo.setItemText(index, tr(label))
        for button in self.navigation_buttons:
            button.apply_language()
        self.pc_panel.apply_language()
        self.rvc_panel.apply_language()
        self.storage_panel.apply_language()
        self._refresh_navigation_summaries()
        self._refresh_history_list(selected_id)
        self._show_selected_detail()

    def refresh(self, *, force: bool = False) -> None:
        self._reload_persisted_tasks()
        self._refresh_tasks(self._queue.tasks())
        self._refresh_current_page(force=force)

    def open_task(self, task_id: str) -> None:
        self._pending_task_id = task_id
        self._select_page(_PAGE_JOBS)
        self.refresh()
        if self._select_task(task_id):
            self._pending_task_id = ""

    def selected_task_id(self) -> str:
        item = self.history_list.currentItem()
        task_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        return task_id if isinstance(task_id, str) else ""

    def closeEvent(self, event) -> None:  # noqa: N802
        self._queue.unsubscribe(self._on_queue_changed)
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop page-owned background work before the Qt object tree is destroyed."""
        self._log_refresh_timer.stop()
        workers = tuple(
            worker
            for worker in (
                self._support_worker,
                self._pc_worker,
                self._rvc_worker,
                self._storage_worker,
                self._cleanup_worker,
            )
            if worker is not None
        )
        for worker in workers:
            worker.request_cancel()
            worker.blockSignals(True)
        terminate_all_commands()
        for worker in workers:
            if worker.isRunning():
                worker.wait()
            worker.deleteLater()
        self._support_worker = None
        self._pc_worker = None
        self._rvc_worker = None
        self._storage_worker = None
        self._cleanup_worker = None

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_responsive_layout()
        self.refresh()
        self._sync_log_timer()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._log_refresh_timer.stop()
        super().hideEvent(event)

    def _on_queue_changed(self, tasks: tuple[ProcessingTask, ...]) -> None:
        signature = tuple((task.task_id, task.status) for task in tasks)
        if signature != self._queue_signature:
            self._cleanup_plan = StorageCleanupPlan(())
            self.storage_panel.set_cleanup_plan(self._cleanup_plan)
        if self.isVisible():
            if signature != self._queue_signature:
                self._reload_persisted_tasks()
            self._refresh_tasks(tasks)

    def _reload_persisted_tasks(self) -> None:
        self._persisted_tasks = tuple(
            _task_from_record(record) for record in self._diagnostics.records()
        )

    def _refresh_tasks(self, tasks: tuple[ProcessingTask, ...]) -> None:
        selected_id = self.selected_task_id() or self._pending_task_id
        self._queue_signature = tuple((task.task_id, task.status) for task in tasks)
        self._tasks = self._merged_tasks(tasks)
        self._tasks_by_id = {task.task_id: task for task in self._tasks}
        self.navigation_buttons[_PAGE_JOBS].set_summary(
            tr("{count} recorded jobs", count=len(self._tasks))
        )
        self._refresh_history_list(selected_id)

    def _merged_tasks(
        self,
        queue_tasks: tuple[ProcessingTask, ...],
    ) -> tuple[DiagnosticTask, ...]:
        records = {task.task_id: task for task in self._persisted_tasks}
        for task in queue_tasks:
            current = records.get(task.task_id)
            if current is None:
                records[task.task_id] = _task_from_processing(task)
                continue
            records[task.task_id] = replace(
                current,
                title=task.title,
                detail=task.detail,
                status=task.status,
                progress=task.progress,
                finished_at=task.finished_at,
                diagnostic_code=task.diagnostic_code or current.diagnostic_code,
                error=task.error or current.error,
                path=task.diagnostic_path or current.path,
            )
        return tuple(
            sorted(
                records.values(),
                key=lambda task: task.finished_at or task.started_at,
                reverse=True,
            )
        )

    def _refresh_history_list(self, selected_task_id: str = "") -> None:
        selected_id = selected_task_id or self.selected_task_id() or self._pending_task_id
        query = self.search_edit.text().strip().casefold()
        status = str(self.status_combo.currentData() or "")
        visible = tuple(
            task
            for task in self._tasks
            if (not status or task.status == status)
            and (
                not query
                or query in task.title.casefold()
                or query in task.detail.casefold()
                or query in task.task_id.casefold()
                or query in task.diagnostic_code.casefold()
            )
        )

        self.history_list.blockSignals(True)
        self.history_list.clear()
        for task in visible:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, tr(task.title))
            item.setToolTip(_history_detail(task))
            row = DiagnosticHistoryRow(task, self.history_list.viewport())
            attach_list_item_widget(self.history_list, item, row)
            item.setSizeHint(QSize(0, _HISTORY_ITEM_HEIGHT))
        self.history_list.blockSignals(False)
        self.history_count_label.setText(f"{len(visible)} / {len(self._tasks)}")
        self.history_list.setVisible(bool(visible))
        self.empty_history_label.setVisible(not visible)
        if selected_id and self._select_task(selected_id):
            return
        if self.history_list.count():
            self.history_list.setCurrentRow(0)
            self._show_selected_detail()
        else:
            self._show_task_detail(None)

    def _select_task(self, task_id: str) -> bool:
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == task_id:
                self.history_list.setCurrentItem(item)
                self._show_task_detail(self._tasks_by_id.get(task_id))
                return True
        return False

    def _on_history_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            row = self.history_list.itemWidget(item)
            if row is None:
                continue
            row.setProperty("selected", item is current)
            row.style().unpolish(row)
            row.style().polish(row)
        self._show_selected_detail()

    def _show_selected_detail(self) -> None:
        self._show_task_detail(self._tasks_by_id.get(self.selected_task_id()))

    def _show_task_detail(self, task: DiagnosticTask | None) -> None:
        self.action_status.clear()
        if task is None:
            self.detail_title.setText(tr("Select a job"))
            self.detail_subtitle.clear()
            self.detail_status.clear()
            self.summary_text.setPlainText(tr("No job selected."))
            self.command_log_text.clear()
            self.environment_text.clear()
            self._set_detail_actions_enabled(False)
            return

        self.detail_title.setText(tr(task.title))
        self.detail_subtitle.setText(
            f"{tr('Task ID')}: {task.task_id}  ·  {task.started_at.astimezone():%Y-%m-%d %H:%M:%S}"
        )
        self.detail_status.setText(_status_label(task))
        self.detail_status.setProperty("status", task.status)
        self.detail_status.style().unpolish(self.detail_status)
        self.detail_status.style().polish(self.detail_status)
        self.summary_text.setPlainText(_format_summary(task))
        self.command_log_text.setPlainText(
            self._diagnostics.read_command_log(task.task_id)
            or tr("No command log entries yet.")
        )
        self.environment_text.setPlainText(_format_environment(task))
        self._set_detail_actions_enabled(task.path is not None)

    def _set_detail_actions_enabled(self, enabled: bool) -> None:
        self.open_task_folder_button.setEnabled(enabled)
        self.copy_button.setEnabled(enabled)
        self.package_button.setEnabled(enabled)

    def _selected_task(self) -> DiagnosticTask | None:
        return self._tasks_by_id.get(self.selected_task_id())

    def _copy_selected_report(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        QApplication.clipboard().setText(self._diagnostics.build_report(task.task_id))
        self._set_action_status("Copied")

    def _open_selected_folder(self) -> None:
        task = self._selected_task()
        if task is not None and task.path is not None:
            self.open_location_requested.emit(task.path)

    def _create_selected_archive(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        archive = self._diagnostics.build_archive(task.task_id)
        if archive is None:
            self._set_action_status("Diagnostic file unavailable")
            return
        self._set_action_status("Diagnostic file ready")
        self.open_location_requested.emit(archive)

    def _create_support_archive(self) -> None:
        if self._support_worker is not None:
            return
        original_text = tr("Create Diagnostics ZIP")
        self.support_button.setEnabled(False)
        self.support_button.setText(tr("Creating Diagnostics ZIP..."))
        worker = TaskWorker(lambda _progress: build_support_archive(self._diagnostics))
        self._support_worker = worker

        def succeeded(result: object) -> None:
            if isinstance(result, Path):
                self.support_button.setText(tr("Diagnostics ZIP ready"))
                self.open_location_requested.emit(result)
            else:
                self.support_button.setText(tr("Diagnostics ZIP unavailable"))

        def failed(_error: str) -> None:
            self.support_button.setText(tr("Diagnostics ZIP unavailable"))

        def cleanup() -> None:
            self._support_worker = None
            self.support_button.setEnabled(True)
            QTimer.singleShot(
                1800,
                lambda: self.support_button.setText(original_text),
            )
            worker.deleteLater()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(failed)
        worker.finished.connect(cleanup)
        worker.start()

    def _set_action_status(self, text: str) -> None:
        self.action_status.setText(tr(text))
        QTimer.singleShot(1800, self.action_status.clear)

    def _show_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        panel = {
            _PAGE_PC: self.pc_panel,
            _PAGE_RVC: self.rvc_panel,
            _PAGE_STORAGE: self.storage_panel,
        }.get(index)
        if panel is not None:
            QTimer.singleShot(0, panel.reset_scroll)
        self._refresh_current_page()
        self._sync_log_timer()

    def _select_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        button = self.navigation_group.button(index)
        if button is not None:
            button.setChecked(True)

    def _apply_responsive_layout(self) -> None:
        compact = self.width() < _COMPACT_LAYOUT_WIDTH
        if compact == self._navigation_compact:
            return
        self._navigation_compact = compact
        navigation_width = 62 if compact else 202
        self.navigation_frame.setMinimumWidth(navigation_width)
        self.navigation_frame.setMaximumWidth(navigation_width)
        self.navigation_frame.setProperty("compact", compact)
        self.navigation_frame.style().unpolish(self.navigation_frame)
        self.navigation_frame.style().polish(self.navigation_frame)
        for button in self.navigation_buttons:
            button.set_compact(compact)
        history_width = 250 if compact else 320
        self.history_panel.setMinimumWidth(240 if compact else 280)
        self.jobs_splitter.setSizes(
            (history_width, max(420, self.jobs_splitter.width() - history_width))
        )

    def _show_detail_tab(self, index: int) -> None:
        self.detail_stack.setCurrentIndex(index)

    def _sync_log_timer(self) -> None:
        if self.isVisible() and self.page_stack.currentIndex() == _TAB_APP_LOG:
            self._log_refresh_timer.start()
        else:
            self._log_refresh_timer.stop()

    def _refresh_visible_log(self) -> None:
        if self.page_stack.currentIndex() == _TAB_APP_LOG:
            self._refresh_app_log()

    def _refresh_app_log(self) -> None:
        text = read_log_tail()
        if text == self._raw_application_log:
            return
        self._raw_application_log = text
        self._apply_app_log_filter()

    def _apply_app_log_filter(self) -> None:
        query = self.log_search_edit.text().strip().casefold()
        level = str(self.log_filter_combo.currentData() or "")
        lines = self._raw_application_log.splitlines()
        if level == "error":
            lines = [line for line in lines if " error " in f" {line.casefold()} "]
        elif level == "warning":
            lines = [
                line
                for line in lines
                if any(token in line.casefold() for token in (" warning ", " warn "))
            ]
        if query:
            lines = [line for line in lines if query in line.casefold()]
        display = "\n".join(lines) or tr("No application log entries yet.")
        if display == self.application_log.toPlainText():
            return
        scroll = self.application_log.verticalScrollBar()
        follow_tail = self.log_auto_scroll_button.isChecked() or (
            scroll.value() >= max(0, scroll.maximum() - 4)
        )
        self.application_log.setPlainText(display)
        if follow_tail:
            scroll.setValue(scroll.maximum())

    def _copy_app_log(self) -> None:
        QApplication.clipboard().setText(self.application_log.toPlainText())

    def _refresh_current_page(self, *, force: bool = False) -> None:
        index = self.page_stack.currentIndex()
        if index == _PAGE_APP_LOG:
            self._refresh_app_log()
        elif index == _PAGE_PC:
            self._refresh_pc_environment(force=force)
        elif index == _PAGE_RVC:
            self._refresh_rvc_environment(force=force)
        elif index == _PAGE_STORAGE:
            self._refresh_storage(force=force)

    def _refresh_navigation_summaries(self) -> None:
        self.navigation_buttons[_PAGE_JOBS].set_summary(
            tr("{count} recorded jobs", count=len(self._tasks))
        )
        self.navigation_buttons[_PAGE_APP_LOG].set_summary("Live application log")
        pc_summary = (
            self._pc_snapshot.selected_adapter_name
            if self._pc_snapshot is not None
            else "Hardware and memory"
        )
        self.navigation_buttons[_PAGE_PC].set_summary(pc_summary)
        rvc_summary = (
            self._rvc_snapshot.active_profile.upper()
            if self._rvc_snapshot is not None
            else "Runtime and acceleration"
        )
        self.navigation_buttons[_PAGE_RVC].set_summary(rvc_summary)
        storage_summary = (
            tr(
                "{free} available",
                free=_format_bytes(self._storage_inventory.disk_free_bytes),
            )
            if self._storage_inventory is not None
            else "Usage and safe cleanup"
        )
        self.navigation_buttons[_PAGE_STORAGE].set_summary(storage_summary)

    def _refresh_pc_environment(self, *, force: bool = False) -> None:
        if self._pc_worker is not None:
            return
        if self._pc_snapshot is not None and not force:
            self.pc_panel.set_snapshot(self._pc_snapshot)
            return
        self.pc_panel.set_loading(True)
        worker = TaskWorker(
            lambda _progress: collect_pc_environment(
                APP_PATHS,
                refresh_hardware=force,
            )
        )
        self._pc_worker = worker

        def succeeded(result: object) -> None:
            if not isinstance(result, PcEnvironmentSnapshot):
                return
            self._pc_snapshot = result
            self.pc_panel.set_snapshot(result)
            summary = result.selected_adapter_name or tr("CPU processing")
            self.navigation_buttons[_PAGE_PC].set_summary(summary)

        def cleanup() -> None:
            self.pc_panel.set_loading(False)
            self._pc_worker = None
            worker.deleteLater()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(self.pc_panel.set_error)
        worker.finished.connect(cleanup)
        worker.start()

    def _refresh_rvc_environment(
        self,
        *,
        deep: bool = False,
        force: bool = False,
    ) -> None:
        if self._rvc_worker is not None:
            return
        if self._rvc_snapshot is not None and not deep and not force:
            self.rvc_panel.set_snapshot(self._rvc_snapshot)
            return
        self.rvc_panel.set_loading(True, deep=deep)
        worker = TaskWorker(
            lambda _progress: collect_rvc_environment_status(
                APP_PATHS,
                deep=deep,
            )
        )
        self._rvc_worker = worker

        def succeeded(result: object) -> None:
            if not isinstance(result, RvcEnvironmentSnapshot):
                return
            self._rvc_snapshot = result
            self.rvc_panel.set_snapshot(result)
            summary = result.active_profile.upper() or tr("Runtime status")
            self.navigation_buttons[_PAGE_RVC].set_summary(summary)

        def cleanup() -> None:
            self.rvc_panel.set_loading(False, deep=deep)
            self._rvc_worker = None
            worker.deleteLater()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(self.rvc_panel.set_error)
        worker.finished.connect(cleanup)
        worker.start()

    def _refresh_storage(self, *, force: bool = False) -> None:
        if self._storage_worker is not None or self._cleanup_worker is not None:
            return
        if self._storage_inventory is not None and not force:
            self.storage_panel.set_inventory(self._storage_inventory)
            self.storage_panel.set_cleanup_plan(self._cleanup_plan)
            return
        self.storage_panel.set_loading(True)
        worker = TaskWorker(lambda progress: scan_storage(APP_PATHS, progress))
        self._storage_worker = worker

        def succeeded(result: object) -> None:
            if not isinstance(result, StorageInventory):
                return
            self._storage_inventory = result
            self._cleanup_plan = build_safe_cleanup_plan(
                APP_PATHS,
                active_jobs=self._has_active_jobs(),
            )
            self.storage_panel.set_inventory(result)
            self.storage_panel.set_cleanup_plan(self._cleanup_plan)
            self.navigation_buttons[_PAGE_STORAGE].set_summary(
                tr("{free} available", free=_format_bytes(result.disk_free_bytes))
            )

        def cleanup() -> None:
            self.storage_panel.set_loading(False)
            self._storage_worker = None
            worker.deleteLater()

        worker.progress_changed.connect(self.storage_panel.set_progress)
        worker.succeeded.connect(succeeded)
        worker.failed.connect(self.storage_panel.set_error)
        worker.finished.connect(cleanup)
        worker.start()

    def _confirm_cleanup(self) -> None:
        if self._cleanup_worker is not None:
            return
        plan = build_safe_cleanup_plan(
            APP_PATHS,
            active_jobs=self._has_active_jobs(),
        )
        self._cleanup_plan = plan
        self.storage_panel.set_cleanup_plan(plan)
        if not plan.candidates:
            return
        message = tr(
            "{size} across {count} files can be removed. "
            "Library audio, models, training work, exports, and the RVC runtime "
            "are not included.",
            size=_format_bytes(plan.reclaimable_bytes),
            count=plan.file_count,
        )
        if not ConfirmationDialog.confirm(
            self,
            tr("Safe Cleanup"),
            message,
            APP_ICON_PATH,
            theme_mode=self._theme_mode,
            accept_label=tr("Clean"),
            cancel_label=tr("Cancel"),
        ):
            return
        refreshed = build_safe_cleanup_plan(
            APP_PATHS,
            active_jobs=self._has_active_jobs(),
        )
        refreshed_paths = {
            candidate.path.resolve(): candidate for candidate in refreshed.candidates
        }
        confirmed = tuple(
            refreshed_paths[path]
            for candidate in plan.candidates
            if (path := candidate.path.resolve()) in refreshed_paths
        )
        dispatch_plan = StorageCleanupPlan(
            confirmed,
            refreshed.skipped_for_active_jobs,
        )
        self._cleanup_plan = dispatch_plan
        self.storage_panel.set_cleanup_plan(dispatch_plan)
        if dispatch_plan.candidates:
            self._execute_cleanup(dispatch_plan)

    def _execute_cleanup(self, plan: StorageCleanupPlan) -> None:
        self.storage_panel.set_cleanup_running(True)
        worker = TaskWorker(
            lambda progress: execute_cleanup(
                plan,
                progress,
                active_jobs=self._has_active_jobs,
                idle_guard=self._queue.run_if_idle,
            )
        )
        self._cleanup_worker = worker

        def succeeded(result: object) -> None:
            if not isinstance(result, StorageCleanupReport):
                return
            self.storage_panel.set_cleanup_result(
                result.reclaimed_bytes,
                len(result.failed_paths),
                len(result.skipped_paths),
            )
            self._storage_inventory = None
            self._cleanup_plan = StorageCleanupPlan(())

        def cleanup() -> None:
            self.storage_panel.set_cleanup_running(False)
            self._cleanup_worker = None
            worker.deleteLater()
            self._refresh_storage(force=True)

        worker.progress_changed.connect(self.storage_panel.set_progress)
        worker.succeeded.connect(succeeded)
        worker.failed.connect(self.storage_panel.set_error)
        worker.finished.connect(cleanup)
        worker.start()

    def _has_active_jobs(self) -> bool:
        active_statuses = {"queued", "running", "stopping"}
        return any(task.status in active_statuses for task in self._queue.tasks())

    @staticmethod
    def _storage_locations() -> tuple[tuple[str, Path], ...]:
        return (
            ("Data", APP_PATHS.workspace_root),
            ("Exports", APP_PATHS.output_root),
            ("Runtime", APP_PATHS.runtime_root),
            ("Cache", APP_PATHS.cache_dir),
        )


class DiagnosticsWindow(AppDialog):
    """Single reusable app-styled diagnostics window."""

    open_location_requested = Signal(object)
    system_setup_requested = Signal()

    def __init__(
        self,
        queue: ProcessingQueue,
        diagnostics: JobDiagnostics,
        parent: QWidget | None = None,
        *,
        theme_mode: str = "white",
    ) -> None:
        super().__init__(
            tr("Environment & Management"),
            APP_ICON_PATH,
            theme_mode=theme_mode,
            parent=parent,
            allow_maximize=True,
        )
        self.setObjectName("DiagnosticsWindow")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(760, 560)
        self.resize(1160, 780)
        self._initial_geometry_applied = False

        self.page = DiagnosticsPage(queue, diagnostics, self)
        self.page.back_button.hide()
        self.page.open_location_requested.connect(self.open_location_requested.emit)
        self.page.system_setup_requested.connect(self.system_setup_requested.emit)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.addWidget(self.page)
        self.page.apply_language()
        self.set_theme_mode(theme_mode)

    def show_diagnostics(self, task_id: str = "") -> None:
        was_hidden = not self.isVisible()
        if task_id:
            self.page.open_task(task_id)
        else:
            self.page.refresh()
        if not self._initial_geometry_applied:
            self._fit_to_available_screen()
            self._initial_geometry_applied = True
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        if was_hidden:
            self._center_on_parent()
        self.raise_()
        self.activateWindow()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.title_bar.set_theme_mode(theme_mode)
        self.page.set_theme_mode(theme_mode)
        self.setStyleSheet(build_stylesheet(theme_mode))

    def apply_language(self) -> None:
        self.setWindowTitle(tr("Environment & Management"))
        self.page.apply_language()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        center = (
            parent.frameGeometry().center()
            if parent is not None and parent.isVisible()
            else available.center()
        )
        x = max(
            available.left(),
            min(
                center.x() - self.width() // 2,
                available.right() - self.width() + 1,
            ),
        )
        y = max(
            available.top(),
            min(
                center.y() - self.height() // 2,
                available.bottom() - self.height() + 1,
            ),
        )
        self.move(x, y)

    def _fit_to_available_screen(self) -> None:
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(self.minimumWidth(), min(1160, available.width() - 32))
        height = max(self.minimumHeight(), min(780, available.height() - 32))
        self.resize(width, height)


class DiagnosticHistoryRow(QWidget):
    def __init__(self, task: DiagnosticTask, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiagnosticHistoryRow")
        self.setProperty("status", task.status)
        self.setFixedHeight(_HISTORY_ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(9)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        self.title_label = _ElidedDiagnosticLabel(
            tr(task.title),
            object_name="DiagnosticHistoryTitle",
            fixed_height=16,
        )
        self.detail_label = _ElidedDiagnosticLabel(
            _history_detail(task),
            object_name="DiagnosticsMutedText",
            fixed_height=15,
        )
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.detail_label)

        status = QLabel(_status_label(task))
        status.setObjectName("DiagnosticsStatusPill")
        status.setProperty("status", task.status)
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(text_layout, 1)
        layout.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)


class _ElidedDiagnosticLabel(QLabel):
    def __init__(
        self,
        text: str,
        *,
        object_name: str,
        fixed_height: int,
    ) -> None:
        super().__init__()
        self._full_text = " ".join(str(text).split())
        self.setObjectName(object_name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(fixed_height)
        self.setToolTip(self._full_text)
        self.setText(self._full_text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                max(0, self.contentsRect().width()),
            )
        )


def _task_from_record(record: JobDiagnosticRecord) -> DiagnosticTask:
    return DiagnosticTask(
        task_id=record.task_id,
        title=record.title,
        detail=record.detail,
        status=record.status,
        progress=record.progress,
        started_at=record.started_at,
        finished_at=record.finished_at,
        diagnostic_code=record.diagnostic_code,
        diagnostic_summary=record.diagnostic_summary,
        error=record.error,
        app_version=record.app_version,
        path=record.path,
        environment=record.environment,
    )


def _history_detail(task: DiagnosticTask) -> str:
    title = tr(task.title).strip().casefold()
    for raw_line in tr(task.detail).splitlines():
        line = " ".join(raw_line.split())
        if line and line.casefold() != title:
            return line
    return task.started_at.astimezone().strftime("%Y-%m-%d %H:%M")


def _task_from_processing(task: ProcessingTask) -> DiagnosticTask:
    return DiagnosticTask(
        task_id=task.task_id,
        title=task.title,
        detail=task.detail,
        status=task.status,
        progress=task.progress,
        started_at=task.created_at,
        finished_at=task.finished_at,
        diagnostic_code=task.diagnostic_code,
        diagnostic_summary="",
        error=task.error,
        app_version="",
        path=task.diagnostic_path,
        environment={},
    )


def _status_label(task: DiagnosticTask) -> str:
    if task.status == "completed":
        return tr("Complete")
    if task.status == "failed":
        return tr("Failed")
    if task.status == "cancelled":
        return tr("Stopped")
    return f"{task.progress}%"


def _format_summary(task: DiagnosticTask) -> str:
    lines = [
        tr(task.title),
        f"{tr('Status')}: {_status_label(task)}",
        f"{tr('Started')}: {task.started_at.astimezone():%Y-%m-%d %H:%M:%S}",
    ]
    if task.finished_at is not None:
        lines.append(
            f"{tr('Finished')}: {task.finished_at.astimezone():%Y-%m-%d %H:%M:%S}"
        )
    lines.extend(
        (
            f"{tr('Task ID')}: {task.task_id}",
            f"{tr('Diagnostic ID')}: {task.diagnostic_code or 'NONE'}",
        )
    )
    if task.diagnostic_summary:
        lines.extend(("", tr(task.diagnostic_summary)))
    if task.detail:
        lines.extend(("", tr(task.detail)))
    if task.error:
        lines.extend(("", tr("Error"), task.error))
    return "\n".join(lines)


def _format_environment(task: DiagnosticTask) -> str:
    environment = task.environment
    if not environment:
        return tr("No environment information is available for this job.")
    labels = (
        ("App", task.app_version),
        ("OS", environment.get("platform")),
        ("Python", environment.get("python")),
        ("RVC backend", environment.get("rvc_backend")),
        ("RVC adapter", environment.get("rvc_adapter")),
        ("RVC desired profile", environment.get("rvc_desired_profile")),
        ("RVC installed profile", environment.get("rvc_installed_profile")),
        ("RVC profile version", environment.get("rvc_profile_version")),
    )
    return "\n".join(f"{label}: {value or '-'}" for label, value in labels)


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
