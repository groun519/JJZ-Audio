from __future__ import annotations

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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.model_add_dialog import (
    ModelAddAction,
    ModelAddDialog,
    ModelImportMode,
    ModelImportSource,
)
from jang_app.qt_app.model_badge import set_model_badge
from jang_app.qt_app.model_dataset_panel import ModelDatasetPanel
from jang_app.qt_app.model_detail_panel import ModelDetailPanel, ModelProfileValues
from jang_app.qt_app.model_row import ModelListRow
from jang_app.qt_app.model_training_panel import (
    ModelTrainingPanel,
    ModelTrainingWorker,
    format_training_elapsed,
)
from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.text_input_dialog import TextInputDialog
from jang_app.qt_app.widgets import FeedbackButton, SvgIconButton
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.command import CommandCancellation
from jang_app.services.model_dataset import ModelDataset, ModelDatasetStore
from jang_app.services.i18n import tr
from jang_app.services.processing_queue import ProcessingQueue
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace
from jang_app.services.rvc_training_finalize import (
    RvcTrainingFinalizeResult,
    finalize_rvc_training_artifacts,
)
from jang_app.services.rvc_training_pipeline import (
    RvcTrainingPipelineResult,
    RvcTrainingStage,
    run_rvc_training_pipeline,
)
from jang_app.services.rvc_training_state import RvcTrainingState, RvcTrainingStateStore
from jang_app.services.rvc_training_train import RvcTrainingRunSettings
from jang_app.services.runtime_installation import installed_rvc_runtime_profile
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_DIRECTML,
    normalize_rvc_profile,
)
from jang_app.services.rvc_training_runtime import training_backend_for_profile


@dataclass(frozen=True)
class _ModelTrainingJobResult:
    pipeline: RvcTrainingPipelineResult
    finalized: RvcTrainingFinalizeResult | None


class ModelWorkspacePage(QWidget):
    use_in_convert_requested = Signal(object)
    open_location_requested = Signal(object)
    preview_started = Signal()

    def __init__(
        self,
        initial_folder: Path,
        workspace: RvcModelWorkspace | None = None,
        processing_queue: ProcessingQueue | None = None,
        execution_runtime_root: Path | None = None,
        runtime_profile: str = "",
    ) -> None:
        super().__init__()
        self._initial_folder = initial_folder.expanduser()
        self._execution_runtime_root = (
            execution_runtime_root or initial_folder
        ).expanduser().resolve()
        self._workspace = workspace or RvcModelWorkspace()
        self._runtime_profile = runtime_profile
        self._records_by_id: dict[str, RvcModelRecord] = {}
        self._rows_by_id: dict[str, ModelListRow] = {}
        self._selected_model_id: str | None = None
        self._active_worker: TaskWorker | None = None
        self._active_action_label = ""
        self._processing_queue = processing_queue
        self._training_worker: ModelTrainingWorker | None = None
        self._training_cancellation: CommandCancellation | None = None
        self._training_model_id = ""
        self._training_task_id = ""
        self._training_progress = 0
        self._training_stage = ""
        self._training_started_at = 0.0
        self._training_last_activity_at = 0.0
        self._training_queue_runtime_bucket = -1
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
        self.training_panel.set_compute_backends(
            inference_backend,
            training_backend_for_profile(profile),
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
        layout.setSpacing(18)
        layout.addWidget(self._build_library_controls(), 0)
        layout.addWidget(self._build_model_library(), 1)
        return view

    def _build_library_controls(self) -> QFrame:
        controls = QFrame()
        controls.setObjectName("Panel")
        controls.setMinimumWidth(270)
        controls.setMaximumWidth(320)
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
        self.add_model_button = FeedbackButton("Add Model")
        self.add_model_button.setObjectName("ModelAddButton")
        self.add_model_button.clicked.connect(self._show_add_model_dialog)
        self.refresh_button = SvgIconButton("refresh", size=30)
        self.refresh_button.setObjectName("ModelIconButton")
        self.refresh_button.setToolTip("Refresh models")
        self.refresh_button.clicked.connect(self.refresh_models)
        library_heading.addWidget(title)
        library_heading.addStretch(1)
        library_heading.addWidget(self.add_model_button)
        library_heading.addWidget(self.refresh_button)

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
        self.workspace_use_button = FeedbackButton("Use in Convert")
        self.workspace_use_button.setObjectName("PrimaryButton")
        self.workspace_use_button.clicked.connect(self._emit_use_selected)

        header_layout.addWidget(self.workspace_back_button)
        header_layout.addLayout(identity)
        header_layout.addWidget(self.workspace_status_badge)
        header_layout.addWidget(self.workspace_mode_badge)
        header_layout.addStretch(1)
        header_layout.addWidget(self.workspace_open_button)
        header_layout.addWidget(self.workspace_use_button)

        section_control = QFrame()
        section_control.setObjectName("SegmentedControl")
        section_control.setMaximumWidth(450)
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
        self.training_section_button = FeedbackButton("Training")
        self.training_section_button.setObjectName("SegmentButton")
        self.training_section_button.setCheckable(True)
        self.section_button_group = QButtonGroup(self)
        self.section_button_group.setExclusive(True)
        self.section_button_group.addButton(self.overview_section_button, 0)
        self.section_button_group.addButton(self.dataset_section_button, 1)
        self.section_button_group.addButton(self.training_section_button, 2)
        self.section_button_group.idClicked.connect(self._navigate_model_section)
        section_layout.addWidget(self.overview_section_button, 1)
        section_layout.addWidget(self.dataset_section_button, 1)
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
        self.dataset_panel = ModelDatasetPanel(ModelDatasetStore(self._workspace.root))
        self.dataset_panel.preview_started.connect(self.preview_started.emit)
        dataset_layout.addWidget(dataset_title)
        dataset_layout.addWidget(self.dataset_panel, 1)

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
        training_layout.addWidget(training_title)
        training_layout.addWidget(self.training_panel, 1)

        self.workspace_content_stack = QStackedWidget()
        self.workspace_content_stack.addWidget(overview)
        self.workspace_content_stack.addWidget(dataset)
        self.workspace_content_stack.addWidget(training)

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
                row = ModelListRow(record)
                row.activated.connect(self._open_model)
                item.setSizeHint(row.sizeHint())
                self.model_list.addItem(item)
                self.model_list.setItemWidget(item, row)
                self._rows_by_id[record.model_id] = row

            selected_index = next(
                (index for index, record in enumerate(records) if record.model_id == previous_selection),
                0,
            )
            self.model_list.setCurrentRow(selected_index)

        self._update_summary(records)
        if not records:
            self._selected_model_id = None
            self.detail_panel.set_record(None)
            self.dataset_panel.set_model(None)
            self.training_panel.set_model(None, None, 0, 0)
            self._update_workspace_header(None)
            self.view_stack.setCurrentIndex(0)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.refresh_button.set_theme_mode(theme_mode)
        self.workspace_back_button.set_theme_mode(theme_mode)
        self.workspace_open_button.set_theme_mode(theme_mode)
        self.detail_panel.set_theme_mode(theme_mode)
        self.dataset_panel.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.detail_panel.apply_language()
        self.dataset_panel.apply_language()
        self.training_panel.apply_language()
        self._navigate_model_section(self.workspace_content_stack.currentIndex())
        self._update_workspace_header(self._selected_record())
        for row in self._rows_by_id.values():
            row.apply_language()
            apply_widget_language(row)
        if self.model_list.count() == 1 and self.model_list.item(0).data(Qt.ItemDataRole.UserRole) is None:
            self.model_list.item(0).setText(tr("No models added"))

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
        self.workspace_use_button.setDisabled(is_busy or selected is None or not selected.can_convert)
        self.import_progress.setVisible(is_busy)
        self.detail_panel.set_busy(is_busy)

    def _on_model_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        model_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._selected_model_id = model_id if isinstance(model_id, str) else None
        for row_id, row in self._rows_by_id.items():
            row.set_selected(row_id == self._selected_model_id)
        selected = self._selected_record()
        self.detail_panel.set_record(selected)
        self.dataset_panel.set_model(selected.model_id if selected is not None else None)
        self._refresh_training_panel(selected)
        self._update_workspace_header(selected)

    def _open_model_from_item(self, item: QListWidgetItem) -> None:
        model_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(model_id, str):
            self._open_model(model_id)

    def _open_model(self, model_id: str) -> None:
        record = self._records_by_id.get(model_id)
        if record is None:
            return
        self._select_model_item(model_id)
        self.detail_panel.set_record(record)
        self.dataset_panel.set_model(record.model_id)
        self._refresh_training_panel(record)
        self._update_workspace_header(record)
        self._navigate_model_section(0)
        self.view_stack.setCurrentIndex(1)

    def _show_model_library(self) -> None:
        self.stop_preview()
        self.view_stack.setCurrentIndex(0)

    def _navigate_model_section(self, index: int) -> None:
        selected_index = max(0, min(2, index))
        self.workspace_content_stack.setCurrentIndex(selected_index)
        self.overview_section_button.setChecked(selected_index == 0)
        self.dataset_section_button.setChecked(selected_index == 1)
        self.training_section_button.setChecked(selected_index == 2)
        section_name = ("Overview", "Dataset", "Training")[selected_index]
        set_translated_text(self.workspace_section_label, section_name)
        if selected_index != 1:
            self.stop_preview()

    def stop_preview(self) -> None:
        self.dataset_panel.stop_preview()

    def shutdown_training(self) -> None:
        if self._training_worker is None:
            return
        self._stop_training()
        self._training_worker.wait()

    def _refresh_training_panel(self, record: RvcModelRecord | None) -> None:
        if record is None or not record.is_managed:
            self.training_panel.set_model(record, None, 0, 0)
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
            dataset = ModelDatasetStore(self._workspace.root).load(record.model_id)
        except Exception as exc:
            self.training_panel.set_model(record, None, 0, 0)
            self.training_panel.set_failure(str(exc))
            return
        training_items = dataset.training_items
        ready_items = sum(item.review_state == REVIEW_READY for item in training_items)
        is_running = self._training_worker is not None and self._training_model_id == record.model_id
        self.training_panel.set_model(record, state, ready_items, len(training_items))
        self.training_panel.set_running(is_running)
        self.dataset_panel.set_training_locked(is_running)
        if is_running:
            self.training_panel.set_progress(self._training_progress)
            self.training_panel.set_stage(self._training_stage)
            self._refresh_training_runtime()

    def _start_training(self, settings: object) -> None:
        record = self._selected_record()
        if self._training_worker is not None or record is None or not record.is_managed:
            return
        if not isinstance(settings, RvcTrainingRunSettings):
            return
        try:
            dataset = ModelDatasetStore(self._workspace.root).load(record.model_id)
            self._validate_training_dataset(dataset)
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
        self.training_panel.set_progress(0)
        state = RvcTrainingStateStore(record.model_id, layout).refresh_checkpoint_pair()
        initial_epoch = state.current_epoch if settings.resume and state.can_resume else 0
        self.training_panel.set_epoch_progress(initial_epoch, settings.target_epoch)
        self.training_panel.set_stage(self._training_stage)
        self.dataset_panel.set_training_locked(True)

        worker = ModelTrainingWorker(
            lambda progress, stage, epoch, activity: self._run_training_job(
                record,
                layout,
                dataset,
                settings,
                cancellation,
                progress,
                stage,
                epoch,
                activity,
            )
        )
        worker.set_diagnostic_task_id(self._training_task_id)
        worker.setParent(self)
        worker.progress_changed.connect(self._on_training_progress)
        worker.stage_changed.connect(self._on_training_stage)
        worker.epoch_changed.connect(self._on_training_epoch)
        worker.activity_changed.connect(self._on_training_activity)
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
        activity: Callable[[], None],
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
            output_callback=lambda _line: activity(),
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

    def _on_training_activity(self) -> None:
        self._mark_training_activity()

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
        if self._processing_queue is not None and self._training_task_id:
            self._processing_queue.fail(self._training_task_id, traceback_text)
        if self._selected_model_id == self._training_model_id:
            self.training_panel.set_failure(traceback_text)
        self.show_status(f"Training failed: {_last_error_line(traceback_text)}")

    def _on_training_finished(self) -> None:
        worker = self._training_worker
        trained_model_id = self._training_model_id
        self._training_worker = None
        self._training_cancellation = None
        self._training_model_id = ""
        self._training_task_id = ""
        self._training_progress = 0
        self._training_stage = ""
        self._training_started_at = 0.0
        self._training_last_activity_at = 0.0
        self._training_queue_runtime_bucket = -1
        self._training_runtime_timer.stop()
        if worker is not None:
            worker.deleteLater()
        if self._selected_model_id == trained_model_id:
            self._refresh_training_panel(self._selected_record())
        else:
            self.dataset_panel.set_training_locked(False)

    def _training_layout(self, record: RvcModelRecord) -> RvcModelPackageLayout:
        return RvcModelPackageLayout(self._workspace.library_dir / record.model_id, record.name)

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
        self.workspace_use_button.setEnabled(record is not None and record.can_convert)

    def _emit_use_selected(self) -> None:
        record = self._selected_record()
        if record is not None and record.can_convert:
            self.use_in_convert_requested.emit(record)

    def _emit_open_selected(self) -> None:
        record = self._selected_record()
        if record is not None:
            self.open_location_requested.emit(record.primary_location)

    def _selected_record(self) -> RvcModelRecord | None:
        if self._selected_model_id is None:
            return None
        return self._records_by_id.get(self._selected_model_id)

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
            self._refresh_training_panel(record)
            self._update_workspace_header(record)
        self._update_summary(list(self._records_by_id.values()))

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
        RvcTrainingStage.TRAIN: "Training",
        RvcTrainingStage.INDEX: "Building Index",
    }[stage]
