from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.model_badge import set_model_badge
from jang_app.qt_app.model_detail_panel import ModelDetailPanel, ModelProfileValues
from jang_app.qt_app.model_row import ModelListRow
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace


class ModelWorkspacePage(QWidget):
    use_in_convert_requested = Signal(object)
    open_location_requested = Signal(object)

    def __init__(self, initial_folder: Path, workspace: RvcModelWorkspace | None = None) -> None:
        super().__init__()
        self._initial_folder = initial_folder.expanduser()
        self._workspace = workspace or RvcModelWorkspace()
        self._records_by_id: dict[str, RvcModelRecord] = {}
        self._rows_by_id: dict[str, ModelListRow] = {}
        self._selected_model_id: str | None = None
        self._active_worker: TaskWorker | None = None
        self._active_action_label = ""
        self._theme_mode = "white"

        self._build_ui()
        self.refresh_models()

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
        controls.setMinimumWidth(330)
        controls.setMaximumWidth(390)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(20, 20, 20, 20)
        controls_layout.setSpacing(16)

        heading = QLabel("Models")
        heading.setObjectName("SectionTitle")

        add_card = QFrame()
        add_card.setObjectName("InsetCard")
        add_layout = QVBoxLayout(add_card)
        add_layout.setContentsMargins(16, 16, 16, 16)
        add_layout.setSpacing(12)

        add_title = QLabel("Add Existing Models")
        add_title.setObjectName("CardTitle")

        self.link_button = QPushButton("Link Folder")
        self.link_button.clicked.connect(self._choose_link_folder)
        self.import_button = QPushButton("Import Copy")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.clicked.connect(self._choose_import_folder)

        add_actions = QHBoxLayout()
        add_actions.setContentsMargins(0, 0, 0, 0)
        add_actions.setSpacing(8)
        add_actions.addWidget(self.link_button, 1)
        add_actions.addWidget(self.import_button, 1)
        add_layout.addWidget(add_title)
        add_layout.addLayout(add_actions)

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
        controls_layout.addWidget(add_card)
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
        self.refresh_button = SvgIconButton("refresh", size=30)
        self.refresh_button.setObjectName("ModelIconButton")
        self.refresh_button.setToolTip("Refresh models")
        self.refresh_button.clicked.connect(self.refresh_models)
        library_heading.addWidget(title)
        library_heading.addStretch(1)
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
        self.workspace_use_button = QPushButton("Use in Convert")
        self.workspace_use_button.setObjectName("PrimaryButton")
        self.workspace_use_button.clicked.connect(self._emit_use_selected)

        header_layout.addWidget(self.workspace_back_button)
        header_layout.addLayout(identity)
        header_layout.addWidget(self.workspace_status_badge)
        header_layout.addWidget(self.workspace_mode_badge)
        header_layout.addStretch(1)
        header_layout.addWidget(self.workspace_open_button)
        header_layout.addWidget(self.workspace_use_button)

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
        layout.addWidget(header)
        layout.addWidget(overview, 1)
        return view

    def refresh_models(self) -> None:
        records = self._workspace.records()
        self._records_by_id = {record.model_id: record for record in records}
        previous_selection = self._selected_model_id
        self.model_list.clear()
        self._rows_by_id.clear()

        if not records:
            empty_item = QListWidgetItem("No models added")
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
            self._update_workspace_header(None)
            self.view_stack.setCurrentIndex(0)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.refresh_button.set_theme_mode(theme_mode)
        self.workspace_back_button.set_theme_mode(theme_mode)
        self.workspace_open_button.set_theme_mode(theme_mode)
        self.detail_panel.set_theme_mode(theme_mode)

    def show_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))

    def _choose_link_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select RVC Model Folder", str(self._initial_folder))
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
        selected = QFileDialog.getExistingDirectory(self, "Select RVC Model Folder", str(self._initial_folder))
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
                "Import Models",
                f"Copy {len(discovered)} models ({_format_size(import_size)}) into JJZero Audio?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_import(folder)

    def _start_import(self, folder: Path) -> None:
        self._set_busy(True)
        self.import_progress.setValue(0)
        self.show_status("Importing model files...")
        worker = TaskWorker(lambda progress: self._workspace.import_folder(folder, progress))
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
        self.link_button.setDisabled(is_busy)
        self.import_button.setDisabled(is_busy)
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
        self._update_workspace_header(record)
        self.view_stack.setCurrentIndex(1)

    def _show_model_library(self) -> None:
        self.view_stack.setCurrentIndex(0)

    def _select_model_item(self, model_id: str) -> None:
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == model_id:
                self.model_list.setCurrentItem(item)
                return

    def _update_workspace_header(self, record: RvcModelRecord | None) -> None:
        self.workspace_title_label.setText(record.title if record is not None else "Model")
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
        selected = QFileDialog.getExistingDirectory(self, "Select RVC Runtime", str(record.runtime_root))
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
    label = QLabel(text)
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
        "inference_model": ("Select RVC Model", "RVC Model (*.pth)"),
        "index_file": ("Select RVC Index", "RVC Index (*.index)"),
        "generator_checkpoint": ("Select Generator Checkpoint", "RVC Checkpoint (G_*.pth)"),
        "discriminator_checkpoint": ("Select Discriminator Checkpoint", "RVC Checkpoint (D_*.pth)"),
    }
    return settings.get(artifact_name, ("Select Model File", "All Files (*)"))


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
