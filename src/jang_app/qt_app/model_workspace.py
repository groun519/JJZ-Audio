from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.confirmation_dialog import ConfirmationDialog
from jang_app.qt_app.model_add_dialog import (
    ModelAddAction,
    ModelAddDialog,
    ModelImportMode,
    ModelImportSource,
)
from jang_app.qt_app.model_badge import set_model_badge
from jang_app.qt_app.model_dataset_analysis_panel import ModelDatasetAnalysisPanel
from jang_app.qt_app.model_dataset_panel import ModelDatasetPanel
from jang_app.qt_app.model_detail_panel import ModelDetailPanel, ModelProfileValues
from jang_app.qt_app.model_precision_benchmark_panel import ModelPrecisionBenchmarkPanel
from jang_app.qt_app.model_row import ModelListRow
from jang_app.qt_app.model_training_panel import (
    ModelTrainingPanel,
    ModelTrainingWorker,
    format_training_elapsed,
)
from jang_app.qt_app.share_progress_action import ShareProgressAction
from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_placeholder,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.text_input_dialog import TextInputDialog
from jang_app.qt_app.widgets import (
    FeedbackButton,
    ScrollSafeComboBox,
    SvgIconButton,
    attach_list_item_widget,
)
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.command import CommandCancellation
from jang_app.services.model_dataset import ModelDataset, ModelDatasetStore
from jang_app.services.model_dataset_analysis import (
    load_cached_model_dataset_analysis,
)
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import classify_error
from jang_app.services.processing_queue import ProcessingQueue
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace
from jang_app.services.rvc_training_activity import describe_rvc_training_activity
from jang_app.services.rvc_training_finalize import (
    RvcTrainingFinalizeResult,
    finalize_rvc_training_artifacts,
)
from jang_app.services.rvc_training_dataset import RvcTrainingDatasetError
from jang_app.services.rvc_training_pipeline import (
    RvcTrainingPipelineResult,
    RvcTrainingStage,
    run_rvc_training_pipeline,
)
from jang_app.services.rvc_training_state import RvcTrainingState, RvcTrainingStateStore
from jang_app.services.rvc_training_train import RvcTrainingRunSettings
from jang_app.services.runtime_installation import installed_rvc_runtime_profile
from jang_app.services.rvc_hardware import RvcComputeBackend, RvcHardwareSelection
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_DIRECTML,
    normalize_rvc_profile,
)
from jang_app.services.rvc_training_preflight import (
    RvcTrainingPreflight,
    inspect_rvc_training_preflight,
)
from jang_app.services.rvc_training_preprocess import (
    RvcTrainingPreprocessError,
    RvcTrainingPreprocessFailure,
    RvcTrainingPreprocessResult,
    load_rvc_preprocess_result,
)
from jang_app.services.rvc_training_runtime import training_backend_for_profile


_LOGGER = logging.getLogger("jang_app")


@dataclass(frozen=True)
class _ModelTrainingJobResult:
    pipeline: RvcTrainingPipelineResult
    finalized: RvcTrainingFinalizeResult | None


class ModelWorkspacePage(QWidget):
    use_in_convert_requested = Signal(object)
    open_location_requested = Signal(object)
    preview_started = Signal()
    log_requested = Signal(str)
    system_setup_requested = Signal()
    models_changed = Signal()
    share_requested = Signal(object)
    delete_share_requested = Signal(object)
    work_share_requested = Signal(object)
    delete_work_share_requested = Signal(object)
    drive_import_requested = Signal(str)

    def __init__(
        self,
        initial_folder: Path,
        workspace: RvcModelWorkspace | None = None,
        processing_queue: ProcessingQueue | None = None,
        execution_runtime_root: Path | None = None,
        runtime_profile: str = "",
        hardware_selection: RvcHardwareSelection | None = None,
    ) -> None:
        super().__init__()
        self._initial_folder = initial_folder.expanduser()
        self._execution_runtime_root = (
            execution_runtime_root or initial_folder
        ).expanduser().resolve()
        self._workspace = workspace or RvcModelWorkspace()
        self._dataset_store = ModelDatasetStore(self._workspace.root)
        self._runtime_profile = runtime_profile
        self._hardware_selection = hardware_selection
        self._records_by_id: dict[str, RvcModelRecord] = {}
        self._rows_by_id: dict[str, ModelListRow] = {}
        self._share_progress_by_id: dict[str, int] = {}
        self._shared_model_ids: set[str] = set()
        self._share_status_provider: Callable[[RvcModelRecord], bool] | None = None
        self._shared_model_work_ids: set[str] = set()
        self._work_share_status_provider: Callable[[RvcModelRecord], bool] | None = None
        self._sharing_enabled = True
        self._selected_model_id: str | None = None
        self._active_worker: TaskWorker | None = None
        self._active_action_label = ""
        self._dataset_load_worker: TaskWorker | None = None
        self._dataset_load_model_id = ""
        self._pending_dataset_model_id = ""
        self._loaded_dataset: ModelDataset | None = None
        self._section_model_ids: dict[int, str] = {}
        self._pending_dataset_open: tuple[str, str, int, int] | None = None
        self._processing_queue = processing_queue
        self._training_worker: ModelTrainingWorker | None = None
        self._training_cancellation: CommandCancellation | None = None
        self._training_model_id = ""
        self._training_task_id = ""
        self._training_progress = 0
        self._training_stage = ""
        self._training_activity_detail = ""
        self._training_started_at = 0.0
        self._training_last_activity_at = 0.0
        self._training_queue_runtime_bucket = -1
        self._benchmark_task_id = ""
        self._benchmark_model_id = ""
        self._benchmark_model_title = ""
        self._theme_mode = "white"

        self._training_runtime_timer = QTimer(self)
        self._training_runtime_timer.setInterval(1000)
        self._training_runtime_timer.timeout.connect(self._refresh_training_runtime)

        self._build_ui()
        self._configure_training_backend()
        self.refresh_models()

    def _configure_training_backend(self) -> None:
        installed = installed_rvc_runtime_profile(self._execution_runtime_root)
        profile = normalize_rvc_profile(
            self._runtime_profile or (installed.profile if installed is not None else "")
        )
        inference_backend = (
            RvcComputeBackend.DIRECTML
            if profile == RVC_PROFILE_DIRECTML
            else training_backend_for_profile(profile)
        )
        adapter = (
            self._hardware_selection.adapter
            if self._hardware_selection is not None
            else None
        )
        self.training_panel.set_compute_backends(
            inference_backend,
            training_backend_for_profile(profile),
            adapter_name=adapter.name if adapter is not None else "",
            adapter_memory_bytes=adapter.adapter_ram if adapter is not None else 0,
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self._build_library_view())
        self.view_stack.addWidget(self._build_model_view())

        self.import_progress = QProgressBar()
        self.import_progress.setObjectName("ModelImportProgress")
        self.import_progress.setRange(0, 100)
        self.import_progress.hide()

        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        layout.addWidget(self.view_stack, 1)
        layout.addWidget(self.import_progress)
        layout.addWidget(self.status_label)

    def _build_library_view(self) -> QWidget:
        view = QWidget()
        layout = QHBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controls = self._build_library_controls()
        library = self._build_model_library()
        self.model_library_splitter = create_workspace_splitter(
            (controls, library),
            object_name="ModelLibraryWorkspaceSplitter",
            sizes=(300, 1300),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        layout.addWidget(self.model_library_splitter, 1)
        return view

    def _build_library_controls(self) -> QFrame:
        controls = QFrame()
        controls.setObjectName("Panel")
        controls.setMinimumWidth(270)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(20, 20, 20, 20)
        controls_layout.setSpacing(16)

        heading = QLabel("Models")
        heading.setObjectName("SectionTitle")

        summary = QFrame()
        summary.setObjectName("ModelSummaryCard")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setHorizontalSpacing(8)
        summary_layout.setVerticalSpacing(4)
        self.total_value = _summary_value("0")
        self.resume_value = _summary_value("0")
        self.managed_value = _summary_value("0")
        summary_layout.addWidget(self.total_value, 0, 0)
        summary_layout.addWidget(self.resume_value, 0, 1)
        summary_layout.addWidget(self.managed_value, 0, 2)
        summary_layout.addWidget(_summary_label("Models"), 1, 0)
        summary_layout.addWidget(_summary_label("Resume"), 1, 1)
        summary_layout.addWidget(_summary_label("Managed"), 1, 2)

        controls_layout.addWidget(heading)
        controls_layout.addWidget(summary)
        controls_layout.addStretch(1)
        return controls

    def _build_model_library(self) -> QFrame:
        library = QFrame()
        library.setObjectName("Panel")
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(20, 20, 20, 20)
        library_layout.setSpacing(14)

        library_heading = QHBoxLayout()
        library_heading.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Model Library")
        title.setObjectName("SectionTitle")
        self.model_library_count_label = QLabel("0 / 0")
        self.model_library_count_label.setObjectName("MutedText")
        self.add_model_button = FeedbackButton("Add Model")
        self.add_model_button.setObjectName("ModelAddButton")
        self.add_model_button.clicked.connect(self._show_add_model_dialog)
        self.refresh_button = SvgIconButton("refresh", size=30)
        self.refresh_button.setObjectName("ModelIconButton")
        self.refresh_button.setToolTip("Refresh models")
        self.refresh_button.clicked.connect(self.refresh_models)
        library_heading.addWidget(title)
        library_heading.addWidget(self.model_library_count_label)
        library_heading.addStretch(1)
        library_heading.addWidget(self.add_model_button)
        library_heading.addWidget(self.refresh_button)

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self.model_search_edit = QLineEdit()
        self.model_search_edit.setClearButtonEnabled(True)
        set_translated_placeholder(self.model_search_edit, "Search models")
        self.model_search_edit.textChanged.connect(self._apply_model_filters)
        self.model_filter_combo = ScrollSafeComboBox()
        self.model_filter_combo.setFixedWidth(170)
        set_translated_tooltip(self.model_filter_combo, "Filter models")
        self.model_filter_combo.currentIndexChanged.connect(self._apply_model_filters)
        self._populate_model_filter_combo()
        filter_layout.addWidget(self.model_search_edit, 1)
        filter_layout.addWidget(self.model_filter_combo)

        list_surface = QFrame()
        list_surface.setObjectName("ModelListSurface")
        list_layout = QVBoxLayout(list_surface)
        list_layout.setContentsMargins(8, 8, 8, 8)
        self.model_list = QListWidget()
        self.model_list.setObjectName("ModelList")
        self.model_list.setSpacing(2)
        self.model_list.currentItemChanged.connect(self._on_model_selection_changed)
        self.model_list.itemActivated.connect(self._open_model_from_item)
        list_layout.addWidget(self.model_list)

        library_layout.addLayout(library_heading)
        library_layout.addLayout(filter_layout)
        library_layout.addWidget(list_surface, 1)
        return library

    def _build_model_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("ModelWorkspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(10)

        self.workspace_back_button = SvgIconButton("arrow_left", size=34)
        self.workspace_back_button.setObjectName("ModelWorkspaceBackButton")
        self.workspace_back_button.setToolTip("All Models")
        self.workspace_back_button.clicked.connect(self._show_model_library)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        self.workspace_title_label = QLabel("Model")
        self.workspace_title_label.setObjectName("ModelWorkspaceTitle")
        self.workspace_section_label = QLabel("Overview")
        self.workspace_section_label.setObjectName("ModelWorkspaceSection")
        identity.addWidget(self.workspace_title_label)
        identity.addWidget(self.workspace_section_label)

        self.workspace_status_badge = QLabel("")
        self.workspace_status_badge.setObjectName("ModelStatusBadge")
        self.workspace_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workspace_mode_badge = QLabel("")
        self.workspace_mode_badge.setObjectName("ModelModeBadge")
        self.workspace_mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.workspace_open_button = SvgIconButton("folder", size=34)
        self.workspace_open_button.setObjectName("ModelIconButton")
        self.workspace_open_button.setToolTip("Open model location")
        self.workspace_open_button.clicked.connect(self._emit_open_selected)

        self.workspace_work_share_action = ShareProgressAction(
            button_size=30,
            share_tooltip="Share model work with Google Drive",
            copy_tooltip="Copy model work Google Drive link",
            delete_tooltip="Delete model work from Google Drive",
            copied_text="Copied",
            button_text="Share Work",
            shared_button_text="Work Link",
            button_width=96,
            parent=header,
        )
        self.workspace_work_share_action.setObjectName("WorkspaceModelWorkShareAction")
        self.workspace_work_share_action.requested.connect(self._emit_work_share_model)
        self.workspace_work_share_action.delete_requested.connect(
            self._emit_delete_work_share_model
        )
        self.workspace_work_share_action.set_actions_expanded(True)

        header_layout.addWidget(self.workspace_back_button)
        header_layout.addLayout(identity)
        header_layout.addWidget(self.workspace_status_badge)
        header_layout.addWidget(self.workspace_mode_badge)
        header_layout.addStretch(1)
        header_layout.addWidget(self.workspace_work_share_action)
        header_layout.addWidget(self.workspace_open_button)

        section_control = QFrame()
        section_control.setObjectName("SegmentedControl")
        section_control.setMaximumWidth(600)
        section_layout = QHBoxLayout(section_control)
        section_layout.setContentsMargins(3, 3, 3, 3)
        section_layout.setSpacing(0)
        self.overview_section_button = FeedbackButton("Overview")
        self.overview_section_button.setObjectName("SegmentButton")
        self.overview_section_button.setCheckable(True)
        self.overview_section_button.setChecked(True)
        self.dataset_section_button = FeedbackButton("Dataset")
        self.dataset_section_button.setObjectName("SegmentButton")
        self.dataset_section_button.setCheckable(True)
        self.analysis_section_button = FeedbackButton("Analysis")
        self.analysis_section_button.setObjectName("SegmentButton")
        self.analysis_section_button.setCheckable(True)
        self.evaluation_section_button = FeedbackButton("Evaluation")
        self.evaluation_section_button.setObjectName("SegmentButton")
        self.evaluation_section_button.setCheckable(True)
        self.training_section_button = FeedbackButton("Training")
        self.training_section_button.setObjectName("SegmentButton")
        self.training_section_button.setCheckable(True)
        self.section_button_group = QButtonGroup(self)
        self.section_button_group.setExclusive(True)
        self.section_button_group.addButton(self.overview_section_button, 0)
        self.section_button_group.addButton(self.dataset_section_button, 1)
        self.section_button_group.addButton(self.analysis_section_button, 2)
        self.section_button_group.addButton(self.evaluation_section_button, 3)
        self.section_button_group.addButton(self.training_section_button, 4)
        self.section_button_group.idClicked.connect(self._navigate_model_section)
        section_layout.addWidget(self.overview_section_button, 1)
        section_layout.addWidget(self.dataset_section_button, 1)
        section_layout.addWidget(self.analysis_section_button, 1)
        section_layout.addWidget(self.evaluation_section_button, 1)
        section_layout.addWidget(self.training_section_button, 1)

        section_row = QHBoxLayout()
        section_row.setContentsMargins(0, 0, 0, 0)
        section_row.addWidget(section_control)
        section_row.addStretch(1)

        overview = QFrame()
        overview.setObjectName("Panel")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(20, 20, 20, 20)
        overview_layout.setSpacing(14)
        overview_title = QLabel("Overview")
        overview_title.setObjectName("SectionTitle")

        self.detail_panel = ModelDetailPanel()
        self.detail_panel.set_workspace_chrome_visible(False)
        self.detail_panel.profile_changed.connect(self._save_model_profile)
        self.detail_panel.artifact_relink_requested.connect(self._choose_artifact_relink)
        self.detail_panel.runtime_relink_requested.connect(self._choose_runtime_relink)
        self.detail_panel.use_requested.connect(self.use_in_convert_requested.emit)
        self.detail_panel.open_location_requested.connect(self.open_location_requested.emit)

        overview_layout.addWidget(overview_title)
        overview_layout.addWidget(self.detail_panel, 1)

        dataset = QFrame()
        dataset.setObjectName("Panel")
        dataset_layout = QVBoxLayout(dataset)
        dataset_layout.setContentsMargins(20, 20, 20, 20)
        dataset_layout.setSpacing(14)
        dataset_title = QLabel("Training Materials")
        dataset_title.setObjectName("SectionTitle")
        self.dataset_panel = ModelDatasetPanel(self._dataset_store)
        self.dataset_panel.preview_started.connect(self.preview_started.emit)
        self.dataset_panel.dataset_changed.connect(self._on_dataset_changed)
        dataset_layout.addWidget(dataset_title)
        dataset_layout.addWidget(self.dataset_panel, 1)

        analysis = QFrame()
        analysis.setObjectName("Panel")
        analysis_layout = QVBoxLayout(analysis)
        analysis_layout.setContentsMargins(20, 20, 20, 20)
        analysis_layout.setSpacing(14)
        analysis_title = QLabel("Training Material Analysis")
        analysis_title.setObjectName("SectionTitle")
        self.analysis_panel = ModelDatasetAnalysisPanel(self._dataset_store)
        self.analysis_panel.edit_requested.connect(self._open_dataset_item)
        analysis_layout.addWidget(analysis_title)
        analysis_layout.addWidget(self.analysis_panel, 1)

        evaluation = QFrame()
        evaluation.setObjectName("Panel")
        evaluation_layout = QVBoxLayout(evaluation)
        evaluation_layout.setContentsMargins(20, 20, 20, 20)
        evaluation_layout.setSpacing(14)
        evaluation_title = QLabel("Model Evaluation")
        evaluation_title.setObjectName("SectionTitle")
        self.evaluation_panel = ModelPrecisionBenchmarkPanel(
            self._workspace.root,
            self._execution_runtime_root,
        )
        self.evaluation_panel.benchmark_started.connect(self._on_benchmark_started)
        self.evaluation_panel.benchmark_progress_reported.connect(
            self._on_benchmark_progress_reported
        )
        self.evaluation_panel.benchmark_completed.connect(self._on_benchmark_completed)
        self.evaluation_panel.benchmark_failed_reported.connect(self._on_benchmark_failed)
        self.evaluation_panel.benchmark_finished_reported.connect(self._on_benchmark_finished)
        evaluation_layout.addWidget(evaluation_title)
        evaluation_layout.addWidget(self.evaluation_panel, 1)

        training = QFrame()
        training.setObjectName("Panel")
        training_layout = QVBoxLayout(training)
        training_layout.setContentsMargins(20, 20, 20, 20)
        training_layout.setSpacing(14)
        training_title = QLabel("Training")
        training_title.setObjectName("SectionTitle")
        self.training_panel = ModelTrainingPanel()
        self.training_panel.start_requested.connect(self._start_training)
        self.training_panel.stop_requested.connect(self._stop_training)
        self.training_panel.diagnostics_requested.connect(
            self._open_training_diagnostics
        )
        self.training_panel.system_setup_requested.connect(
            self.system_setup_requested.emit
        )
        self.training_panel.preflight_requested.connect(
            lambda: self._refresh_training_panel(
                self._selected_record(),
                self._selected_dataset(),
            )
        )
        self.training_panel.excluded_clip_requested.connect(
            self._open_excluded_training_clip
        )
        training_layout.addWidget(training_title)
        training_layout.addWidget(self.training_panel, 1)

        self.training_scroll = QScrollArea()
        self.training_scroll.setObjectName("ModelTrainingScroll")
        self.training_scroll.setWidgetResizable(True)
        self.training_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.training_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.training_scroll.setWidget(training)

        self.workspace_content_stack = QStackedWidget()
        self.workspace_content_stack.addWidget(overview)
        self.workspace_content_stack.addWidget(dataset)
        self.workspace_content_stack.addWidget(analysis)
        self.workspace_content_stack.addWidget(evaluation)
        self.workspace_content_stack.addWidget(self.training_scroll)

        layout.addWidget(header)
        layout.addLayout(section_row)
        layout.addWidget(self.workspace_content_stack, 1)
        return view

    def refresh_models(self) -> None:
        records = self._workspace.records()
        self._records_by_id = {record.model_id: record for record in records}
        previous_selection = self._selected_model_id
        self.model_list.clear()
        self._rows_by_id.clear()

        if not records:
            empty_item = QListWidgetItem(tr("No models added"))
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.model_list.addItem(empty_item)
        else:
            for record in records:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, record.model_id)
                row = ModelListRow(record, self.model_list.viewport())
                row.activated.connect(self._open_model)
                row.share_requested.connect(self._emit_share_model)
                row.delete_share_requested.connect(self._emit_delete_share_model)
                row.remove_requested.connect(self._remove_model)
                row.set_theme_mode(self._theme_mode)
                row.set_sharing_enabled(self._sharing_enabled)
                row.set_shared(self._record_is_shared(record))
                if record.model_id in self._share_progress_by_id:
                    row.set_share_started()
                    row.set_share_progress(self._share_progress_by_id[record.model_id])
                attach_list_item_widget(self.model_list, item, row)
                self._rows_by_id[record.model_id] = row

            selected_index = next(
                (index for index, record in enumerate(records) if record.model_id == previous_selection),
                0,
            )
            self.model_list.setCurrentRow(selected_index)

        self._update_summary(records)
        self._apply_model_filters()
        self.models_changed.emit()
        if not records:
            self._selected_model_id = None
            self.detail_panel.set_record(None)
            self.dataset_panel.set_model(None)
            self.analysis_panel.set_model(None)
            self.evaluation_panel.set_model(None)
            self.training_panel.set_model(None, None, 0, 0)
            self._update_workspace_header(None)
            self.view_stack.setCurrentIndex(0)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.refresh_button.set_theme_mode(theme_mode)
        self.workspace_back_button.set_theme_mode(theme_mode)
        self.workspace_open_button.set_theme_mode(theme_mode)
        self.workspace_work_share_action.set_theme_mode(theme_mode)
        for row in self._rows_by_id.values():
            row.set_theme_mode(theme_mode)
        self.detail_panel.set_theme_mode(theme_mode)
        self.dataset_panel.set_theme_mode(theme_mode)
        self.analysis_panel.set_theme_mode(theme_mode)
        self.evaluation_panel.set_theme_mode(theme_mode)

    def set_sharing_enabled(self, is_enabled: bool) -> None:
        self._sharing_enabled = is_enabled
        for row in self._rows_by_id.values():
            row.set_sharing_enabled(is_enabled)
        self._sync_workspace_work_share_action(self._selected_record())

    def set_share_status_provider(
        self,
        provider: Callable[[RvcModelRecord], bool],
    ) -> None:
        self._share_status_provider = provider
        for model_id, record in self._records_by_id.items():
            is_shared = self._record_is_shared(record, refresh=True)
            row = self._rows_by_id.get(model_id)
            if row is not None:
                row.set_shared(is_shared)

    def set_work_share_status_provider(
        self,
        provider: Callable[[RvcModelRecord], bool],
    ) -> None:
        self._work_share_status_provider = provider
        self._sync_workspace_work_share_action(self._selected_record(), refresh=True)

    def set_share_started(self, model_id: str) -> None:
        if model_id not in self._records_by_id:
            return
        self._share_progress_by_id[model_id] = 0
        row = self._rows_by_id.get(model_id)
        if row is not None:
            row.set_share_started()

    def set_share_progress(self, model_id: str, progress: int) -> None:
        if model_id not in self._share_progress_by_id:
            return
        value = max(0, min(100, int(progress)))
        self._share_progress_by_id[model_id] = value
        row = self._rows_by_id.get(model_id)
        if row is not None:
            row.set_share_progress(value)

    def set_share_completed(self, model_id: str) -> None:
        self._share_progress_by_id.pop(model_id, None)
        self._shared_model_ids.add(model_id)
        row = self._rows_by_id.get(model_id)
        if row is not None:
            row.set_share_completed()

    def set_share_failed(self, model_id: str) -> None:
        self._share_progress_by_id.pop(model_id, None)
        row = self._rows_by_id.get(model_id)
        if row is not None:
            row.set_share_failed()

    def set_share_deleted(self, model_id: str) -> None:
        self._share_progress_by_id.pop(model_id, None)
        self._shared_model_ids.discard(model_id)
        row = self._rows_by_id.get(model_id)
        if row is not None:
            row.set_share_deleted()

    def set_work_share_started(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if record is None or self._selected_model_id != model_id:
            return
        self.workspace_work_share_action.set_running(True)
        self.workspace_work_share_action.set_feature_enabled(
            self._sharing_enabled and record.is_managed
        )

    def set_work_share_progress(self, model_id: str, progress: int) -> None:
        if self._selected_model_id != model_id:
            return
        self.workspace_work_share_action.set_progress(progress)

    def set_work_share_completed(self, model_id: str) -> None:
        if self._selected_model_id == model_id:
            self.workspace_work_share_action.set_completed()
        self._shared_model_work_ids.add(model_id)

    def set_work_share_failed(self, model_id: str) -> None:
        if self._selected_model_id != model_id:
            return
        self.workspace_work_share_action.set_failed()

    def set_work_share_deleted(self, model_id: str) -> None:
        self._shared_model_work_ids.discard(model_id)
        if self._selected_model_id == model_id:
            self.workspace_work_share_action.set_deleted()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._populate_model_filter_combo()
        self.detail_panel.apply_language()
        self.dataset_panel.apply_language()
        self.analysis_panel.apply_language()
        self.evaluation_panel.apply_language()
        self.training_panel.apply_language()
        self.workspace_work_share_action.apply_language()
        self._navigate_model_section(self.workspace_content_stack.currentIndex())
        self._update_workspace_header(self._selected_record())
        for row in self._rows_by_id.values():
            row.apply_language()
            apply_widget_language(row)
        if self.model_list.count() == 1 and self.model_list.item(0).data(Qt.ItemDataRole.UserRole) is None:
            self.model_list.item(0).setText(tr("No models added"))
        self._apply_model_filters()

    def _populate_model_filter_combo(self) -> None:
        current = (
            self.model_filter_combo.currentData()
            if self.model_filter_combo.count()
            else "all"
        )
        self.model_filter_combo.blockSignals(True)
        self.model_filter_combo.clear()
        for label, value in (
            ("All Models", "all"),
            ("Managed", "managed"),
            ("Linked", "linked"),
            ("Conversion Ready", "convert"),
            ("Needs Attention", "attention"),
        ):
            self.model_filter_combo.addItem(tr(label), value)
        index = self.model_filter_combo.findData(current)
        self.model_filter_combo.setCurrentIndex(index if index >= 0 else 0)
        self.model_filter_combo.blockSignals(False)

    def _apply_model_filters(self, *_args: object) -> None:
        query = self.model_search_edit.text().strip().casefold()
        filter_mode = str(self.model_filter_combo.currentData() or "all")
        visible_count = 0
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            model_id = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(model_id, str):
                continue
            record = self._records_by_id.get(model_id)
            is_visible = record is not None and self._record_matches_model_filter(
                record,
                query,
                filter_mode,
            )
            item.setHidden(not is_visible)
            visible_count += int(is_visible)
        self.model_library_count_label.setText(
            f"{visible_count} / {len(self._records_by_id)}"
        )

    @staticmethod
    def _record_matches_model_filter(
        record: RvcModelRecord,
        query: str,
        filter_mode: str,
    ) -> bool:
        searchable = " ".join(
            (
                record.title,
                record.name,
                *record.tags,
                record.status_label,
                record.mode_label,
            )
        ).casefold()
        if query and query not in searchable:
            return False
        if filter_mode == "managed":
            return record.is_managed
        if filter_mode == "linked":
            return not record.is_managed
        if filter_mode == "convert":
            return record.can_convert
        if filter_mode == "attention":
            return record.status_key in {"missing", "checkpoint", "incomplete"}
        return True

    def show_status(self, message: str) -> None:
        set_translated_text(self.status_label, message)
        self.status_label.setVisible(bool(message))

    def _create_model(self) -> None:
        name, accepted = TextInputDialog.get_text(
            self,
            tr("New Model"),
            tr("Model Name"),
            APP_ICON_PATH,
            theme_mode=self._theme_mode,
            accept_label=tr("Create"),
            cancel_label=tr("Cancel"),
        )
        if not accepted:
            return
        try:
            record = self._workspace.create_model(name, self._initial_folder)
        except Exception as exc:
            self.show_status(f"Create failed: {_last_error_line(exc)}")
            return
        self._selected_model_id = record.model_id
        self.refresh_models()
        self._open_model(record.model_id)
        self._navigate_model_section(1)
        self.show_status("Model created.")

    def _remove_model(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if record is None:
            return
        if self._model_has_active_task(model_id):
            self.show_status("Stop the current model task before deleting it.")
            return

        message = (
            tr(
                "Delete '{name}' and all model files, training material, edited clips, "
                "analysis results, and checkpoints managed by JJZero Audio? This cannot be undone.",
                name=record.title,
            )
            if record.is_managed
            else tr(
                "Remove '{name}' and all JJZero Audio training work for it? "
                "Linked external model files will not be deleted. This cannot be undone.",
                name=record.title,
            )
        )
        if not ConfirmationDialog.confirm(
            self,
            tr("Delete Model"),
            message,
            APP_ICON_PATH,
            theme_mode=self._theme_mode,
            accept_label=tr("Delete"),
            cancel_label=tr("Cancel"),
        ):
            return

        self.stop_preview()
        try:
            self._workspace.remove_model(model_id)
        except Exception as exc:
            self.show_status(f"Delete failed: {_last_error_line(exc)}")
            return

        if self._selected_model_id == model_id:
            self._selected_model_id = None
            self._loaded_dataset = None
            self._pending_dataset_model_id = ""
            self._pending_dataset_open = None
            self._section_model_ids.clear()
        self._share_progress_by_id.pop(model_id, None)
        self._shared_model_ids.discard(model_id)
        self._shared_model_work_ids.discard(model_id)
        self.view_stack.setCurrentIndex(0)
        self.refresh_models()
        self.show_status("Model deleted.")

    def _model_has_active_task(self, model_id: str) -> bool:
        if self._active_worker is not None:
            return True
        if self._dataset_load_worker is not None and self._dataset_load_model_id == model_id:
            return True
        if self._training_worker is not None and self._training_model_id == model_id:
            return True
        if self._benchmark_model_id == model_id:
            return True
        if model_id in self._share_progress_by_id:
            return True
        if self._selected_model_id != model_id:
            return False
        return any(
            getattr(panel, "_worker", None) is not None
            for panel in (self.dataset_panel, self.analysis_panel, self.evaluation_panel)
        )

    def _show_add_model_dialog(self) -> None:
        request = ModelAddDialog.get_request(
            self,
            APP_ICON_PATH,
            theme_mode=self._theme_mode,
        )
        if request is None:
            return
        if request.action == ModelAddAction.CREATE:
            self._create_model()
            return
        if request.source == ModelImportSource.DRIVE_LINK:
            self.drive_import_requested.emit(request.link)
            return
        if request.source == ModelImportSource.INFERENCE_FILE:
            self._choose_inference_file(request.mode)
            return
        if request.mode == ModelImportMode.LINKED:
            self._choose_link_folder()
        else:
            self._choose_import_folder()

    def _choose_inference_file(self, mode: ModelImportMode) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            tr("Select RVC Inference Model"),
            str(self._initial_folder),
            tr("RVC Inference Model (*.pth)"),
        )
        if not selected:
            return
        model_file = Path(selected)
        if mode == ModelImportMode.MANAGED:
            self._start_import_task(
                lambda progress: [self._workspace.import_inference_file(model_file, progress)]
            )
            return
        try:
            record = self._workspace.link_inference_file(model_file)
        except Exception as exc:
            self.show_status(f"Link failed: {_last_error_line(exc)}")
            return
        self._selected_model_id = record.model_id
        self.refresh_models()
        index_status = "Index detected." if record.has_index else "PTH-only inference model."
        self.show_status(f"Linked {record.title}. {index_status}")

    def _choose_link_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("Select RVC Model Folder"), str(self._initial_folder))
        if not selected:
            return
        try:
            linked = self._workspace.link_folder(Path(selected))
        except Exception as exc:
            self.show_status(f"Link failed: {_last_error_line(exc)}")
            return
        self._selected_model_id = linked[0].model_id if linked else None
        self.refresh_models()
        self.show_status(f"Linked {len(linked)} model{'s' if len(linked) != 1 else ''} as read-only.")

    def _choose_import_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("Select RVC Model Folder"), str(self._initial_folder))
        if not selected:
            return
        folder = Path(selected)
        try:
            discovered = self._workspace.inspect_folder(folder)
        except Exception as exc:
            self.show_status(f"Import failed: {_last_error_line(exc)}")
            return

        import_size = sum(model.import_size_bytes for model in discovered)
        if import_size >= 1024**3:
            answer = QMessageBox.question(
                self,
                tr("Import Models"),
                tr(
                    "Copy {count} models ({size}) into JJZero Audio?",
                    count=len(discovered),
                    size=_format_size(import_size),
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_import_task(
            lambda progress: self._workspace.import_folder(folder, progress)
        )

    def _start_import_task(
        self,
        task: Callable[[Callable[[int], None]], object],
    ) -> None:
        self._set_busy(True)
        self.import_progress.setValue(0)
        self.show_status("Importing model files...")
        worker = TaskWorker(task)
        worker.setParent(self)
        worker.progress_changed.connect(self.import_progress.setValue)
        worker.succeeded.connect(self._on_import_succeeded)
        worker.failed.connect(self._on_import_failed)
        worker.finished.connect(self._on_worker_finished)
        self._active_worker = worker
        worker.start()

    def _on_import_succeeded(self, records: object) -> None:
        imported = records if isinstance(records, list) else []
        self._selected_model_id = imported[0].model_id if imported else None
        self.refresh_models()
        self.show_status(f"Imported {len(imported)} managed model{'s' if len(imported) != 1 else ''}.")

    def _on_import_failed(self, traceback_text: str) -> None:
        self.show_status(f"Import failed: {_last_error_line(traceback_text)}")

    def _on_worker_finished(self) -> None:
        worker = self._active_worker
        self._active_worker = None
        self._active_action_label = ""
        self._set_busy(False)
        if worker is not None:
            worker.deleteLater()

    def _set_busy(self, is_busy: bool) -> None:
        self.add_model_button.setDisabled(is_busy)
        self.refresh_button.setDisabled(is_busy)
        self.workspace_back_button.setDisabled(is_busy)
        selected = self._selected_record()
        self.workspace_open_button.setDisabled(is_busy or selected is None or not selected.primary_location.exists())
        self.workspace_work_share_action.setDisabled(is_busy)
        self.import_progress.setVisible(is_busy)
        self.detail_panel.set_busy(is_busy)

    def _on_model_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        model_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        previous_model_id = self._selected_model_id
        self._selected_model_id = model_id if isinstance(model_id, str) else None
        if self._selected_model_id != previous_model_id:
            self._loaded_dataset = None
            self._pending_dataset_model_id = ""
            self._pending_dataset_open = None
            self._section_model_ids.clear()
        for row_id, row in self._rows_by_id.items():
            row.set_selected(row_id == self._selected_model_id)
        selected = self._selected_record()
        self.detail_panel.set_record(selected)
        if selected is None:
            self.dataset_panel.set_model(None)
            self.analysis_panel.set_model(None)
            self.evaluation_panel.set_model(None)
            self.training_panel.set_model(None, None, 0, 0)
        self._update_workspace_header(selected)
        self._sync_workspace_work_share_action(selected)

    def _open_model_from_item(self, item: QListWidgetItem) -> None:
        model_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(model_id, str):
            self._open_model(model_id)

    def _open_model(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if record is None:
            return
        self._navigate_model_section(0)
        if self._selected_model_id != model_id:
            self._select_model_item(model_id)
        self.view_stack.setCurrentIndex(1)
        QTimer.singleShot(0, lambda: self._request_dataset_load_if_current(model_id))

    def _show_model_library(self) -> None:
        self.stop_preview()
        self.view_stack.setCurrentIndex(0)

    def _navigate_model_section(self, index: int) -> None:
        selected_index = max(0, min(4, index))
        self.workspace_content_stack.setCurrentIndex(selected_index)
        self.overview_section_button.setChecked(selected_index == 0)
        self.dataset_section_button.setChecked(selected_index == 1)
        self.analysis_section_button.setChecked(selected_index == 2)
        self.evaluation_section_button.setChecked(selected_index == 3)
        self.training_section_button.setChecked(selected_index == 4)
        section_name = ("Overview", "Dataset", "Analysis", "Evaluation", "Training")[selected_index]
        set_translated_text(self.workspace_section_label, section_name)
        if selected_index != 1:
            self.stop_preview()
        self._ensure_model_section_loaded(selected_index)

    def _ensure_model_section_loaded(self, section_index: int) -> None:
        record = self._selected_record()
        if record is None or section_index == 0:
            return
        model_id = record.model_id
        if section_index == 1:
            if self._section_model_ids.get(section_index) == model_id:
                return
            self.dataset_panel.prepare_model(model_id)
            self._section_model_ids[section_index] = model_id
            dataset = self._selected_dataset()
            if dataset is not None:
                self.dataset_panel.apply_dataset(dataset, deferred=True)
                self._try_open_pending_dataset_item()
            else:
                self._request_dataset_load(model_id)
            return
        if section_index == 2:
            if self._section_model_ids.get(section_index) != model_id:
                self.analysis_panel.set_model(model_id)
                self._section_model_ids[section_index] = model_id
            self.analysis_panel.ensure_analysis()
            return
        if section_index == 3:
            if self._section_model_ids.get(section_index) != model_id:
                self.evaluation_panel.set_model(record)
                self._section_model_ids[section_index] = model_id
            return
        if self._section_model_ids.get(section_index) == model_id:
            return
        dataset = self._selected_dataset()
        if dataset is None:
            self.training_panel.set_model(record, None, 0, 0)
            self._request_dataset_load(model_id)
            return
        self._refresh_training_panel(record, dataset)
        self._section_model_ids[section_index] = model_id

    def _request_dataset_load_if_current(self, model_id: str) -> None:
        if self._selected_model_id == model_id and self.view_stack.currentIndex() == 1:
            self._request_dataset_load(model_id)

    def _request_dataset_load(self, model_id: str) -> None:
        if self._loaded_dataset is not None and self._loaded_dataset.model_id == model_id:
            return
        self._pending_dataset_model_id = model_id
        if self._dataset_load_worker is not None:
            return
        self._start_pending_dataset_load()

    def _start_pending_dataset_load(self) -> None:
        model_id = self._pending_dataset_model_id
        if not model_id:
            return
        self._dataset_load_model_id = model_id
        worker = TaskWorker(lambda _progress: self._dataset_store.load(model_id))
        worker.setParent(self)
        worker.succeeded.connect(
            lambda result, selected_model_id=model_id: self._on_dataset_load_succeeded(
                selected_model_id,
                result,
            )
        )
        worker.failed.connect(
            lambda traceback_text, selected_model_id=model_id: self._on_dataset_load_failed(
                selected_model_id,
                traceback_text,
            )
        )
        worker.finished.connect(
            lambda selected_worker=worker, selected_model_id=model_id: self._on_dataset_load_finished(
                selected_worker,
                selected_model_id,
            )
        )
        self._dataset_load_worker = worker
        worker.start()

    def _on_dataset_load_succeeded(self, model_id: str, result: object) -> None:
        if self._pending_dataset_model_id == model_id:
            self._pending_dataset_model_id = ""
        if not isinstance(result, ModelDataset) or self._selected_model_id != model_id:
            return
        self._loaded_dataset = result
        section_index = self.workspace_content_stack.currentIndex()
        if section_index == 1 and self._section_model_ids.get(1) == model_id:
            self.dataset_panel.apply_dataset(result, deferred=True)
            self._try_open_pending_dataset_item()
        elif section_index == 4:
            record = self._selected_record()
            self._refresh_training_panel(record, result)
            self._section_model_ids[4] = model_id

    def _on_dataset_load_failed(self, model_id: str, traceback_text: str) -> None:
        if self._pending_dataset_model_id == model_id:
            self._pending_dataset_model_id = ""
        if self._selected_model_id != model_id:
            return
        self._section_model_ids.pop(1, None)
        if self.workspace_content_stack.currentIndex() == 1:
            self.dataset_panel.set_load_failure(model_id, traceback_text)
        elif self.workspace_content_stack.currentIndex() == 4:
            self.training_panel.set_failure(_last_error_line(traceback_text))

    def _on_dataset_load_finished(self, worker: TaskWorker, model_id: str) -> None:
        if self._dataset_load_worker is worker:
            self._dataset_load_worker = None
            self._dataset_load_model_id = ""
        worker.deleteLater()
        if self._pending_dataset_model_id and self._pending_dataset_model_id != model_id:
            self._start_pending_dataset_load()

    def _on_dataset_changed(self, dataset: object) -> None:
        if isinstance(dataset, ModelDataset) and dataset.model_id == self._selected_model_id:
            self._loaded_dataset = dataset
        self.analysis_panel.mark_stale()
        self._section_model_ids.pop(4, None)
        if self.workspace_content_stack.currentIndex() == 4:
            self._ensure_model_section_loaded(4)

    def _open_dataset_item(
        self,
        item_id: str,
        clip_id: str = "",
        start_ms: int = 0,
        end_ms: int = 0,
    ) -> None:
        self._pending_dataset_open = (item_id, clip_id, start_ms, end_ms)
        self._navigate_model_section(1)
        self._try_open_pending_dataset_item()

    def _try_open_pending_dataset_item(self) -> None:
        pending = self._pending_dataset_open
        if pending is None or self._selected_dataset() is None:
            return
        if self.dataset_panel.open_training_item(*pending):
            self._pending_dataset_open = None

    def _open_excluded_training_clip(self, failure: object) -> None:
        if not isinstance(failure, RvcTrainingPreprocessFailure):
            return
        if not failure.source_item_id:
            self.show_status("This excluded input is no longer linked to a training clip.")
            return
        self._open_dataset_item(failure.source_item_id, failure.source_clip_id)
        self.show_status("Excluded clip opened for review.")

    def _set_preprocess_summary(self, result: RvcTrainingPreprocessResult) -> None:
        self.training_panel.set_preprocess_summary(
            len(result.snapshot.inputs),
            result.successful_input_count,
            result.failed_inputs,
        )

    def stop_preview(self) -> None:
        self.dataset_panel.stop_preview()

    def shutdown_training(self) -> None:
        if self._training_worker is not None:
            self._stop_training()
            self._training_worker.wait()
        if self._dataset_load_worker is not None:
            self._dataset_load_worker.wait()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_preview()
        self.shutdown_training()
        super().closeEvent(event)

    def _refresh_training_panel(
        self,
        record: RvcModelRecord | None,
        dataset: ModelDataset | None = None,
    ) -> None:
        if record is None or not record.is_managed:
            self.training_panel.set_model(record, None, 0, 0)
            self.training_panel.clear_preprocess_summary()
            self.dataset_panel.set_training_locked(False)
            return
        layout = self._training_layout(record)
        try:
            state_store = RvcTrainingStateStore(record.model_id, layout)
            if self._training_model_id == record.model_id and self._training_worker is not None:
                state = state_store.load()
            else:
                state = state_store.recover_interrupted()
                state = state_store.refresh_checkpoint_pair()
            dataset = dataset or self._dataset_store.load(record.model_id)
        except Exception as exc:
            self.training_panel.set_model(record, None, 0, 0)
            self.training_panel.clear_preprocess_summary()
            self.training_panel.set_failure(str(exc))
            return
        training_items = dataset.training_items
        ready_items = sum(item.review_state == REVIEW_READY for item in training_items)
        total_duration_ms = sum(item.training_duration_ms for item in training_items)
        preflight = self._training_preflight(record, dataset)
        is_running = self._training_worker is not None and self._training_model_id == record.model_id
        self.training_panel.set_model(
            record,
            state,
            ready_items,
            len(training_items),
            total_duration_ms,
            preflight,
        )
        try:
            preprocess_result = load_rvc_preprocess_result(record.model_id, layout)
        except (RvcTrainingDatasetError, RvcTrainingPreprocessError):
            self.training_panel.clear_preprocess_summary()
        else:
            self._set_preprocess_summary(preprocess_result)
        self.training_panel.set_running(is_running)
        self.dataset_panel.set_training_locked(is_running)
        if is_running:
            self.training_panel.set_progress(self._training_progress)
            self.training_panel.set_stage(self._training_stage)
            self.training_panel.set_activity_detail(self._training_activity_detail)
            self._refresh_training_runtime()

    def _start_training(self, settings: object) -> None:
        record = self._selected_record()
        if self._training_worker is not None or record is None or not record.is_managed:
            return
        if not isinstance(settings, RvcTrainingRunSettings):
            return
        try:
            dataset = self._selected_dataset() or self._dataset_store.load(record.model_id)
            self._loaded_dataset = dataset
            self._validate_training_dataset(dataset)
            preflight = self._training_preflight(record, dataset)
            if not preflight.can_start:
                blocker = preflight.blockers[0]
                raise ValueError(
                    tr(blocker.detail, **blocker.format_values)
                )
            settings.validate()
        except Exception as exc:
            self.training_panel.set_failure(str(exc))
            return

        layout = self._training_layout(record)
        cancellation = CommandCancellation()
        self._training_cancellation = cancellation
        self._training_model_id = record.model_id
        self._training_progress = 0
        self._training_stage = "Preparing Training"
        self._training_activity_detail = ""
        now = monotonic()
        self._training_started_at = now
        self._training_last_activity_at = now
        self._training_queue_runtime_bucket = -1
        self._training_task_id = (
            self._processing_queue.start("Train RVC Model", record.title)
            if self._processing_queue is not None
            else ""
        )
        self.training_panel.set_running(True)
        self.training_panel.clear_preprocess_summary()
        self.training_panel.set_progress(0)
        state = RvcTrainingStateStore(record.model_id, layout).refresh_checkpoint_pair()
        initial_epoch = state.current_epoch if settings.resume and state.can_resume else 0
        self.training_panel.set_epoch_progress(initial_epoch, settings.target_epoch)
        self.training_panel.set_stage(self._training_stage)
        self.dataset_panel.set_training_locked(True)

        worker = ModelTrainingWorker(
            lambda progress, stage, epoch, activity, preprocess: self._run_training_job(
                record,
                layout,
                dataset,
                settings,
                cancellation,
                progress,
                stage,
                epoch,
                activity,
                preprocess,
            )
        )
        worker.set_diagnostic_task_id(self._training_task_id)
        worker.setParent(self)
        worker.progress_changed.connect(self._on_training_progress)
        worker.stage_changed.connect(self._on_training_stage)
        worker.epoch_changed.connect(self._on_training_epoch)
        worker.activity_changed.connect(self._on_training_activity)
        worker.preprocess_changed.connect(self._on_training_preprocess)
        worker.succeeded.connect(self._on_training_succeeded)
        worker.failed.connect(self._on_training_failed)
        worker.finished.connect(self._on_training_finished)
        self._training_worker = worker
        self._training_runtime_timer.start()
        self._refresh_training_runtime()
        worker.start()

    def _run_training_job(
        self,
        record: RvcModelRecord,
        layout: RvcModelPackageLayout,
        dataset: ModelDataset,
        settings: RvcTrainingRunSettings,
        cancellation: CommandCancellation,
        progress: Callable[[int], None],
        stage: Callable[[str], None],
        epoch: Callable[[int, int], None],
        activity: Callable[[str], None],
        preprocess: Callable[[object], None],
    ) -> _ModelTrainingJobResult:
        pipeline = run_rvc_training_pipeline(
            record.model_id,
            layout,
            self._execution_runtime_root,
            dataset,
            settings,
            cancellation=cancellation,
            progress=progress,
            epoch_callback=epoch,
            stage_callback=lambda current: stage(_training_stage_label(current)),
            preprocess_callback=preprocess,
            output_callback=lambda line: activity(
                describe_rvc_training_activity(line) or ""
            ),
        )
        if pipeline.stopped:
            return _ModelTrainingJobResult(pipeline, None)
        stage("Registering Model")
        finalized = finalize_rvc_training_artifacts(
            self._workspace,
            record.model_id,
            layout,
            self._execution_runtime_root,
        )
        return _ModelTrainingJobResult(pipeline, finalized)

    def _stop_training(self) -> None:
        if self._training_cancellation is None:
            return
        self._mark_training_activity()
        self._training_stage = "Stopping Training"
        self.training_panel.set_stage(self._training_stage)
        self._update_training_queue_detail()
        self._training_cancellation.request_cancel()

    def _on_training_progress(self, value: int) -> None:
        self._mark_training_activity()
        self._training_progress = max(0, min(100, int(value)))
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_progress(self._training_progress)
        if self._processing_queue is not None and self._training_task_id:
            self._processing_queue.update_progress(self._training_task_id, self._training_progress)

    def _on_training_stage(self, stage: str) -> None:
        self._mark_training_activity()
        self._training_stage = stage
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_stage(stage)
        self._update_training_queue_detail()

    def _on_training_epoch(self, current_epoch: int, target_epoch: int) -> None:
        self._mark_training_activity()
        if self._processing_queue is not None and self._training_task_id:
            diagnostics = self._processing_queue.diagnostics
            if diagnostics is not None:
                diagnostics.event(
                    self._training_task_id,
                    "training_epoch",
                    current_epoch=current_epoch,
                    target_epoch=target_epoch,
                )
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_epoch_progress(current_epoch, target_epoch)

    def _on_training_activity(self, detail: str = "") -> None:
        self._mark_training_activity()
        if detail:
            self._training_activity_detail = detail
        if detail and self._selected_model_id == self._training_model_id:
            self.training_panel.set_activity_detail(detail)

    def _on_training_preprocess(self, result: object) -> None:
        if not isinstance(result, RvcTrainingPreprocessResult):
            return
        self._mark_training_activity()
        if self._selected_model_id == self._training_model_id:
            self._set_preprocess_summary(result)
        if result.failed_inputs:
            _LOGGER.warning(
                "Training audio preparation excluded clips: model=%s used=%s total=%s excluded=%s",
                self._training_model_id,
                result.successful_input_count,
                len(result.snapshot.inputs),
                result.skipped_input_count,
            )

    def _mark_training_activity(self) -> None:
        if self._training_worker is not None:
            self._training_last_activity_at = monotonic()

    def _refresh_training_runtime(self) -> None:
        if self._training_worker is None or self._training_started_at <= 0:
            self._training_runtime_timer.stop()
            return
        now = monotonic()
        elapsed = max(0, int(now - self._training_started_at))
        idle = max(0, int(now - self._training_last_activity_at))
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_runtime_status(elapsed, idle)
        bucket = elapsed // 5
        if bucket != self._training_queue_runtime_bucket:
            self._training_queue_runtime_bucket = bucket
            self._update_training_queue_detail(elapsed)

    def _update_training_queue_detail(self, elapsed_seconds: int | None = None) -> None:
        if self._processing_queue is None or not self._training_task_id:
            return
        if elapsed_seconds is None:
            elapsed_seconds = max(0, int(monotonic() - self._training_started_at))
        stage = tr(self._training_stage) if self._training_stage else tr("Training")
        elapsed = tr("Elapsed {elapsed}", elapsed=format_training_elapsed(elapsed_seconds))
        self._processing_queue.update_detail(self._training_task_id, f"{stage}  |  {elapsed}")

    def _on_training_succeeded(self, result: object) -> None:
        if not isinstance(result, _ModelTrainingJobResult):
            self._on_training_failed("Training returned an invalid result.")
            return
        if result.pipeline.stopped:
            if self._processing_queue is not None and self._training_task_id:
                self._processing_queue.cancel(self._training_task_id)
            self.show_status("Training stopped.")
            return
        if result.finalized is None:
            self._on_training_failed("Training artifacts were not registered.")
            return
        self._apply_updated_record(result.finalized.record)
        if self._processing_queue is not None and self._training_task_id:
            self._processing_queue.complete(self._training_task_id)
        self.show_status("Training completed.")

    def _on_training_failed(self, traceback_text: str) -> None:
        task_id = self._training_task_id
        diagnostic_code = classify_error(traceback_text).code
        if self._processing_queue is not None and self._training_task_id:
            self._processing_queue.fail(self._training_task_id, traceback_text)
        record = self._records_by_id.get(self._training_model_id)
        if record is not None:
            try:
                RvcTrainingStateStore(
                    record.model_id,
                    self._training_layout(record),
                ).record_failure_context(
                    traceback_text,
                    task_id=task_id,
                    diagnostic_code=diagnostic_code,
                )
            except Exception:
                _LOGGER.exception(
                    "Failed to persist training recovery context for model %s",
                    record.model_id,
                )
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_failure(
                traceback_text,
                task_id=task_id,
                diagnostic_code=diagnostic_code,
            )
        self.show_status(f"Training failed: {_last_error_line(traceback_text)}")

    def _open_training_diagnostics(self, task_id: str) -> None:
        if not task_id or self._processing_queue is None:
            return
        if any(task.task_id == task_id for task in self._processing_queue.tasks()):
            self.log_requested.emit(task_id)
            return
        diagnostics = self._processing_queue.diagnostics
        if diagnostics is None:
            return
        path = diagnostics.job_path(task_id)
        if path.exists():
            self.open_location_requested.emit(path)

    def _on_training_finished(self) -> None:
        worker = self._training_worker
        trained_model_id = self._training_model_id
        self._training_worker = None
        self._training_cancellation = None
        self._training_model_id = ""
        self._training_task_id = ""
        self._training_progress = 0
        self._training_stage = ""
        self._training_activity_detail = ""
        self._training_started_at = 0.0
        self._training_last_activity_at = 0.0
        self._training_queue_runtime_bucket = -1
        self._training_runtime_timer.stop()
        if worker is not None:
            worker.deleteLater()
        if self._selected_model_id == trained_model_id:
            self._refresh_training_panel(
                self._selected_record(),
                self._selected_dataset(),
            )
        else:
            self.dataset_panel.set_training_locked(False)

    def _on_benchmark_started(self, model_id: str, model_title: str) -> None:
        self._benchmark_model_id = model_id
        self._benchmark_model_title = model_title
        self._benchmark_task_id = (
            self._processing_queue.start(tr("Model Evaluation"), model_title)
            if self._processing_queue is not None
            else ""
        )
        if self._benchmark_task_id:
            self.evaluation_panel.assign_diagnostic_task_id(self._benchmark_task_id)

    def _on_benchmark_progress_reported(self, progress: int, detail: str) -> None:
        if self._processing_queue is None or not self._benchmark_task_id:
            return
        self._processing_queue.update_progress(self._benchmark_task_id, progress)
        queue_detail = detail
        if self._benchmark_model_title:
            queue_detail = f"{self._benchmark_model_title}  |  {detail}"
        self._processing_queue.update_detail(self._benchmark_task_id, queue_detail)

    def _on_benchmark_completed(self, model_id: str, _model_title: str) -> None:
        if model_id != self._benchmark_model_id:
            return
        if self._processing_queue is not None and self._benchmark_task_id:
            self._processing_queue.complete(self._benchmark_task_id)

    def _on_benchmark_failed(self, model_id: str, _model_title: str, traceback_text: str) -> None:
        if model_id != self._benchmark_model_id:
            return
        if self._processing_queue is not None and self._benchmark_task_id:
            self._processing_queue.fail(self._benchmark_task_id, traceback_text)

    def _on_benchmark_finished(self, model_id: str, _model_title: str) -> None:
        if model_id != self._benchmark_model_id:
            return
        self._benchmark_task_id = ""
        self._benchmark_model_id = ""
        self._benchmark_model_title = ""

    def _training_layout(self, record: RvcModelRecord) -> RvcModelPackageLayout:
        return RvcModelPackageLayout(self._workspace.library_dir / record.model_id, record.name)

    def _training_preflight(
        self,
        record: RvcModelRecord,
        dataset: ModelDataset,
    ) -> RvcTrainingPreflight:
        selection = self._hardware_selection
        adapter = selection.adapter if selection is not None else None
        installed = installed_rvc_runtime_profile(self._execution_runtime_root)
        profile = normalize_rvc_profile(
            self._runtime_profile or (installed.profile if installed is not None else "")
        )
        return inspect_rvc_training_preflight(
            managed_model=record.is_managed,
            dataset=dataset,
            analysis=load_cached_model_dataset_analysis(
                self._dataset_store,
                record.model_id,
            ),
            runtime_root=self._execution_runtime_root,
            workspace_root=self._workspace.root,
            training_backend=training_backend_for_profile(profile),
            adapter_name=adapter.name if adapter is not None else "",
            adapter_memory_bytes=adapter.adapter_ram if adapter is not None else 0,
        )

    @staticmethod
    def _validate_training_dataset(dataset: ModelDataset) -> None:
        training_items = dataset.training_items
        if not training_items:
            raise ValueError("Add training materials before starting.")
        if any(item.review_state != REVIEW_READY for item in training_items):
            raise ValueError("Mark every training material ready before starting.")

    def _select_model_item(self, model_id: str) -> None:
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == model_id:
                self.model_list.setCurrentItem(item)
                return

    def _update_workspace_header(self, record: RvcModelRecord | None) -> None:
        if record is not None:
            self.workspace_title_label.setText(record.title)
        else:
            set_translated_text(self.workspace_title_label, "Model")
        set_model_badge(
            self.workspace_status_badge,
            record.status_label if record is not None else "",
            "status",
            record.status_key if record is not None else "",
        )
        set_model_badge(
            self.workspace_mode_badge,
            record.mode_label if record is not None else "",
            "managed",
            record.is_managed if record is not None else False,
        )
        self.workspace_open_button.setEnabled(record is not None and record.primary_location.exists())
        self._sync_workspace_work_share_action(record)

    def _emit_open_selected(self) -> None:
        record = self._selected_record()
        if record is not None:
            self.open_location_requested.emit(record.primary_location)

    def _emit_share_model(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if self._sharing_enabled and record is not None and record.can_convert:
            self.share_requested.emit(record)

    def _emit_delete_share_model(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if (
            self._sharing_enabled
            and model_id in self._shared_model_ids
            and record is not None
        ):
            self.delete_share_requested.emit(record)

    def _emit_work_share_model(self) -> None:
        record = self._selected_record()
        if self._sharing_enabled and record is not None and record.is_managed:
            self.work_share_requested.emit(record)

    def _emit_delete_work_share_model(self) -> None:
        record = self._selected_record()
        if (
            self._sharing_enabled
            and record is not None
            and record.model_id in self._shared_model_work_ids
        ):
            self.delete_work_share_requested.emit(record)

    def _record_is_shared(
        self,
        record: RvcModelRecord,
        *,
        refresh: bool = False,
    ) -> bool:
        if not refresh and record.model_id in self._shared_model_ids:
            return True
        is_shared = False
        if self._share_status_provider is not None:
            try:
                is_shared = self._share_status_provider(record)
            except OSError:
                is_shared = False
        if is_shared:
            self._shared_model_ids.add(record.model_id)
        else:
            self._shared_model_ids.discard(record.model_id)
        return is_shared

    def _record_work_is_shared(
        self,
        record: RvcModelRecord,
        *,
        refresh: bool = False,
    ) -> bool:
        if not refresh and record.model_id in self._shared_model_work_ids:
            return True
        is_shared = False
        if self._work_share_status_provider is not None:
            try:
                is_shared = self._work_share_status_provider(record)
            except OSError:
                is_shared = False
        if is_shared:
            self._shared_model_work_ids.add(record.model_id)
        else:
            self._shared_model_work_ids.discard(record.model_id)
        return is_shared

    def _sync_workspace_work_share_action(
        self,
        record: RvcModelRecord | None,
        *,
        refresh: bool = False,
    ) -> None:
        enabled = bool(
            self._sharing_enabled and record is not None and record.is_managed
        )
        self.workspace_work_share_action.set_feature_enabled(enabled)
        if not enabled or record is None:
            self.workspace_work_share_action.set_running(False)
            self.workspace_work_share_action.set_shared(False)
            return
        self.workspace_work_share_action.set_shared(
            self._record_work_is_shared(record, refresh=refresh)
        )

    def apply_drive_import(self, records: tuple[RvcModelRecord, ...]) -> None:
        if records:
            self._selected_model_id = records[0].model_id
        self.refresh_models()
        if records:
            self._open_model(records[0].model_id)
            self.show_status(f"Imported {records[0].title} from Google Drive.")
        self.models_changed.emit()

    def _selected_record(self) -> RvcModelRecord | None:
        if self._selected_model_id is None:
            return None
        return self._records_by_id.get(self._selected_model_id)

    def _selected_dataset(self) -> ModelDataset | None:
        dataset = self._loaded_dataset
        if dataset is None or dataset.model_id != self._selected_model_id:
            return None
        return dataset

    def _save_model_profile(self, values: ModelProfileValues) -> None:
        try:
            updated = self._workspace.update_profile(
                values.model_id,
                display_name=values.display_name,
                tags=values.tags,
                notes=values.notes,
                default_pitch=values.default_pitch,
                default_device=values.default_device,
            )
        except Exception as exc:
            self.show_status(f"Profile failed: {_last_error_line(exc)}")
            return
        self._apply_updated_record(updated, refresh_panel=False)
        self.show_status("Model profile updated.")

    def _choose_artifact_relink(self, artifact_name: str) -> None:
        record = self._selected_record()
        if record is None:
            return
        title, file_filter = _artifact_dialog_settings(artifact_name)
        current = getattr(record, artifact_name, None)
        initial_path = current.parent if isinstance(current, Path) else record.source_folder
        selected, _filter = QFileDialog.getOpenFileName(self, title, str(initial_path), file_filter)
        if not selected:
            return
        self._start_artifact_relink(record.model_id, artifact_name, Path(selected))

    def _start_artifact_relink(self, model_id: str, artifact_name: str, path: Path) -> None:
        action_label = _artifact_label(artifact_name)
        self._set_busy(True)
        self.import_progress.setValue(0)
        self._active_action_label = action_label
        self.show_status(f"Updating {action_label.lower()}...")
        worker = TaskWorker(lambda progress: self._workspace.replace_artifact(model_id, artifact_name, path, progress))
        worker.setParent(self)
        worker.progress_changed.connect(self.import_progress.setValue)
        worker.succeeded.connect(self._on_artifact_relinked)
        worker.failed.connect(self._on_artifact_relink_failed)
        worker.finished.connect(self._on_worker_finished)
        self._active_worker = worker
        worker.start()

    def _on_artifact_relinked(self, record: object) -> None:
        if not isinstance(record, RvcModelRecord):
            return
        self._apply_updated_record(record)
        self.show_status(f"{self._active_action_label} updated.")

    def _on_artifact_relink_failed(self, traceback_text: str) -> None:
        self.show_status(f"Update failed: {_last_error_line(traceback_text)}")

    def _choose_runtime_relink(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        selected = QFileDialog.getExistingDirectory(self, tr("Select RVC Runtime"), str(record.runtime_root))
        if not selected:
            return
        try:
            updated = self._workspace.replace_runtime_root(record.model_id, Path(selected))
        except Exception as exc:
            self.show_status(f"Runtime failed: {_last_error_line(exc)}")
            return
        self._apply_updated_record(updated)
        self.show_status("Runtime updated.")

    def _apply_updated_record(self, record: RvcModelRecord, *, refresh_panel: bool = True) -> None:
        self._records_by_id[record.model_id] = record
        row = self._rows_by_id.get(record.model_id)
        if row is not None:
            row.update_record(record)
        if record.model_id == self._selected_model_id:
            if refresh_panel:
                self.detail_panel.set_record(record)
            else:
                self.detail_panel.apply_saved_record(record)
            self._section_model_ids.pop(3, None)
            self._section_model_ids.pop(4, None)
            current_section = self.workspace_content_stack.currentIndex()
            if current_section in {3, 4}:
                self._ensure_model_section_loaded(current_section)
            self._update_workspace_header(record)
        self._update_summary(list(self._records_by_id.values()))
        self._apply_model_filters()
        self.models_changed.emit()

    def _update_summary(self, records: list[RvcModelRecord]) -> None:
        self.total_value.setText(str(len(records)))
        self.resume_value.setText(str(sum(record.can_resume for record in records)))
        self.managed_value.setText(str(sum(record.is_managed for record in records)))


def _summary_value(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("ModelSummaryValue")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _summary_label(text: str) -> QLabel:
    label = QLabel(tr(text))
    label.setObjectName("ModelSummaryLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} GB"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.0f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _artifact_dialog_settings(artifact_name: str) -> tuple[str, str]:
    settings = {
        "inference_model": (tr("Select RVC Model"), "RVC Model (*.pth)"),
        "index_file": (tr("Select RVC Index"), "RVC Index (*.index)"),
        "generator_checkpoint": (tr("Select Generator Checkpoint"), "RVC Checkpoint (G_*.pth)"),
        "discriminator_checkpoint": (tr("Select Discriminator Checkpoint"), "RVC Checkpoint (D_*.pth)"),
    }
    return settings.get(artifact_name, (tr("Select Model File"), tr("All Files (*)")))


def _artifact_label(artifact_name: str) -> str:
    return {
        "inference_model": "Model",
        "index_file": "Index",
        "generator_checkpoint": "Generator checkpoint",
        "discriminator_checkpoint": "Discriminator checkpoint",
    }.get(artifact_name, "Model file")


def _last_error_line(error: object) -> str:
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"


def _training_stage_label(stage: RvcTrainingStage) -> str:
    return {
        RvcTrainingStage.SNAPSHOT: "Preparing Training",
        RvcTrainingStage.PREPROCESS: "Preparing Audio",
        RvcTrainingStage.EXTRACT: "Extracting Features",
        RvcTrainingStage.FILELIST: "Building File List",
        RvcTrainingStage.SPECTROGRAM: "Preparing Spectrograms",
        RvcTrainingStage.TRAIN: "Training Model",
        RvcTrainingStage.INDEX: "Building Index",
    }[stage]
