from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.model_badge import set_model_badge
from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton, ScrollSafeComboBox, ScrollSafeSpinBox, SvgIconButton
from jang_app.services.i18n import tr
from jang_app.services.rvc_model_workspace import RvcModelRecord


@dataclass(frozen=True)
class ModelProfileValues:
    model_id: str
    display_name: str
    tags: tuple[str, ...]
    notes: str
    default_pitch: int
    default_device: str


class ModelDetailPanel(QFrame):
    profile_changed = Signal(object)
    artifact_relink_requested = Signal(str)
    runtime_relink_requested = Signal()
    use_requested = Signal(object)
    open_location_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ModelDetailSurface")
        self.setMinimumWidth(390)
        self._record: RvcModelRecord | None = None
        self._is_loading = False
        self._theme_mode = "white"

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._emit_profile_changed)

        self._build_ui()
        self.set_record(None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.identity_widget = QWidget()
        identity_layout = QVBoxLayout(self.identity_widget)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(8)

        self.title_label = QLabel("Select a model")
        self.title_label.setObjectName("ModelDetailTitle")
        self.title_label.setWordWrap(True)

        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(8)
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("ModelStatusBadge")
        self.status_badge.setMinimumWidth(102)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_badge = QLabel("")
        self.mode_badge.setObjectName("ModelModeBadge")
        self.mode_badge.setMinimumWidth(68)
        self.mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badges.addWidget(self.status_badge)
        badges.addWidget(self.mode_badge)
        badges.addStretch(1)
        identity_layout.addWidget(self.title_label)
        identity_layout.addLayout(badges)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ModelDetailScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_content.setObjectName("ModelDetailContent")
        scroll_layout = QGridLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setHorizontalSpacing(12)
        scroll_layout.setVerticalSpacing(12)

        profile_card = QFrame()
        profile_card.setObjectName("ModelMaintenanceCard")
        profile_layout = QGridLayout(profile_card)
        profile_layout.setContentsMargins(14, 14, 14, 14)
        profile_layout.setHorizontalSpacing(10)
        profile_layout.setVerticalSpacing(10)

        profile_title = QLabel("Profile")
        profile_title.setObjectName("CardTitle")
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setObjectName("ModelProfileInput")
        self.display_name_edit.setMaxLength(80)
        self.tags_edit = QLineEdit()
        self.tags_edit.setObjectName("ModelProfileInput")
        self.tags_edit.setMaxLength(220)
        self.pitch_spin = ScrollSafeSpinBox()
        self.pitch_spin.setObjectName("ModelProfileInput")
        self.pitch_spin.setRange(-9999, 9999)
        self.device_combo = ScrollSafeComboBox()
        self.device_combo.setObjectName("ModelProfileInput")
        self.device_combo.addItems(["cuda:0", "cpu"])
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setObjectName("ModelNotesInput")
        self.notes_edit.setMinimumHeight(60)
        self.notes_edit.setMaximumHeight(72)

        profile_layout.addWidget(profile_title, 0, 0, 1, 4)
        profile_layout.addWidget(_field_label("Name"), 1, 0)
        profile_layout.addWidget(self.display_name_edit, 1, 1, 1, 3)
        profile_layout.addWidget(_field_label("Tags"), 2, 0)
        profile_layout.addWidget(self.tags_edit, 2, 1, 1, 3)
        profile_layout.addWidget(_field_label("Pitch"), 3, 0)
        profile_layout.addWidget(self.pitch_spin, 3, 1)
        profile_layout.addWidget(_field_label("Device"), 3, 2)
        profile_layout.addWidget(self.device_combo, 3, 3)
        profile_layout.addWidget(_field_label("Notes"), 4, 0, Qt.AlignmentFlag.AlignTop)
        profile_layout.addWidget(self.notes_edit, 4, 1, 1, 3)
        profile_layout.setColumnStretch(1, 1)
        profile_layout.setColumnStretch(3, 2)

        files_card = QFrame()
        files_card.setObjectName("ModelMaintenanceCard")
        files_layout = QVBoxLayout(files_card)
        files_layout.setContentsMargins(14, 14, 14, 14)
        files_layout.setSpacing(6)
        files_title = QLabel("Files")
        files_title.setObjectName("CardTitle")
        files_layout.addWidget(files_title)

        self.artifact_rows = {
            "runtime_root": ArtifactRepairRow("Runtime", "runtime_root"),
            "inference_model": ArtifactRepairRow("Model", "inference_model"),
            "index_file": ArtifactRepairRow("Index", "index_file"),
            "generator_checkpoint": ArtifactRepairRow("Generator", "generator_checkpoint"),
            "discriminator_checkpoint": ArtifactRepairRow("Discriminator", "discriminator_checkpoint"),
        }
        for artifact_name, row in self.artifact_rows.items():
            if artifact_name == "runtime_root":
                row.relink_requested.connect(lambda _name: self.runtime_relink_requested.emit())
            else:
                row.relink_requested.connect(self.artifact_relink_requested.emit)
            files_layout.addWidget(row)

        self.source_label = QLabel("")
        self.source_label.setObjectName("ModelSourcePath")
        self.source_label.setWordWrap(True)

        scroll_layout.addWidget(profile_card, 0, 0)
        scroll_layout.addWidget(files_card, 0, 1)
        scroll_layout.addWidget(self.source_label, 1, 0, 1, 2)
        scroll_layout.setColumnStretch(0, 1)
        scroll_layout.setColumnStretch(1, 1)
        scroll_layout.setRowStretch(2, 1)
        self.scroll.setWidget(scroll_content)

        self.actions_widget = QWidget()
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.use_button = FeedbackButton("Use in Convert")
        self.use_button.setObjectName("PrimaryButton")
        self.use_button.clicked.connect(self._emit_use_requested)
        self.open_button = SvgIconButton("folder", size=36)
        self.open_button.setObjectName("ModelIconButton")
        self.open_button.setToolTip("Open model location")
        self.open_button.clicked.connect(self._emit_open_requested)
        actions.addWidget(self.use_button, 1)
        actions.addWidget(self.open_button)

        layout.addWidget(self.identity_widget)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.actions_widget)

        self.display_name_edit.editingFinished.connect(self._queue_profile_save)
        self.tags_edit.editingFinished.connect(self._queue_profile_save)
        self.pitch_spin.valueChanged.connect(self._queue_profile_save)
        self.device_combo.currentIndexChanged.connect(self._queue_profile_save)
        self.notes_edit.textChanged.connect(self._queue_profile_save)

    def set_record(self, record: RvcModelRecord | None) -> None:
        self._save_timer.stop()
        self._record = record
        self._is_loading = True
        try:
            self._populate_record(record)
        finally:
            self._is_loading = False

    def apply_saved_record(self, record: RvcModelRecord) -> None:
        self._record = record
        self.title_label.setText(record.title)
        self.display_name_edit.setText(record.display_name)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.open_button.set_theme_mode(theme_mode)
        for row in self.artifact_rows.values():
            row.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        if self._record is None:
            set_translated_text(self.title_label, "Select a model")
        else:
            set_model_badge(self.status_badge, self._record.status_label, "status", self._record.status_key)
            set_model_badge(self.mode_badge, self._record.mode_label, "managed", self._record.is_managed)
            self.source_label.setText(f"{tr('Source location')}\n{_source_display_path(self._record)}")
        for row in self.artifact_rows.values():
            row.apply_language()

    def set_busy(self, is_busy: bool) -> None:
        for row in self.artifact_rows.values():
            row.setDisabled(is_busy)
        self.use_button.setDisabled(is_busy or self._record is None or not self._record.can_convert)

    def set_workspace_chrome_visible(self, is_visible: bool) -> None:
        self.identity_widget.setVisible(is_visible)
        self.actions_widget.setVisible(is_visible)
        self.setMinimumWidth(390 if is_visible else 0)
        self.setMaximumWidth(470 if is_visible else 16777215)

    def _populate_record(self, record: RvcModelRecord | None) -> None:
        is_available = record is not None
        if record is not None:
            self.title_label.setText(record.title)
        else:
            set_translated_text(self.title_label, "Select a model")
        set_model_badge(
            self.status_badge,
            record.status_label if record else "",
            "status",
            record.status_key if record else "",
        )
        set_model_badge(
            self.mode_badge,
            record.mode_label if record else "",
            "managed",
            record.is_managed if record else False,
        )

        self.display_name_edit.setEnabled(is_available)
        self.tags_edit.setEnabled(is_available)
        self.pitch_spin.setEnabled(is_available)
        self.device_combo.setEnabled(is_available)
        self.notes_edit.setEnabled(is_available)
        self.display_name_edit.setText(record.display_name if record else "")
        self.display_name_edit.setPlaceholderText(record.name if record else "")
        self.tags_edit.setText(", ".join(record.tags) if record else "")
        self.pitch_spin.setValue(record.default_pitch if record else 0)
        self.device_combo.setCurrentText(record.default_device if record else "cuda:0")
        self.notes_edit.setPlainText(record.notes if record else "")

        if record is None:
            for row in self.artifact_rows.values():
                row.set_value(None, "Not linked")
                row.setEnabled(False)
            self.source_label.clear()
            self.use_button.setEnabled(False)
            self.open_button.setEnabled(False)
            return

        self.artifact_rows["runtime_root"].set_value(
            record.runtime_root,
            "Ready" if record.runtime_ready else "Missing",
        )
        self.artifact_rows["inference_model"].set_value(
            record.inference_model,
            _file_state(record.inference_model),
        )
        self.artifact_rows["index_file"].set_value(record.index_file, _file_state(record.index_file))
        checkpoint_state = "Ready" if record.checkpoint_pair_ready else "Mismatch"
        self.artifact_rows["generator_checkpoint"].set_value(
            record.generator_checkpoint,
            checkpoint_state if record.generator_checkpoint is not None else "Not linked",
        )
        self.artifact_rows["discriminator_checkpoint"].set_value(
            record.discriminator_checkpoint,
            checkpoint_state if record.discriminator_checkpoint is not None else "Not linked",
        )
        for row in self.artifact_rows.values():
            row.setEnabled(True)
        self.source_label.setText(f"{tr('Source location')}\n{_source_display_path(record)}")
        self.source_label.setToolTip(str(record.source_folder))
        self.use_button.setEnabled(record.can_convert)
        self.open_button.setEnabled(record.primary_location.exists())

    def _queue_profile_save(self, *_args) -> None:
        if self._is_loading or self._record is None:
            return
        self._save_timer.start()

    def _emit_profile_changed(self) -> None:
        record = self._record
        if record is None:
            return
        tags = tuple(part.strip() for part in self.tags_edit.text().split(",") if part.strip())
        self.profile_changed.emit(
            ModelProfileValues(
                model_id=record.model_id,
                display_name=self.display_name_edit.text(),
                tags=tags,
                notes=self.notes_edit.toPlainText(),
                default_pitch=self.pitch_spin.value(),
                default_device=self.device_combo.currentText(),
            )
        )

    def _emit_use_requested(self) -> None:
        if self._record is not None and self._record.can_convert:
            self.use_requested.emit(self._record)

    def _emit_open_requested(self) -> None:
        if self._record is not None:
            self.open_location_requested.emit(self._record.primary_location)


class ArtifactRepairRow(QFrame):
    relink_requested = Signal(str)

    def __init__(self, label: str, artifact_name: str) -> None:
        super().__init__()
        self.setObjectName("ArtifactRepairRow")
        self._artifact_name = artifact_name
        self._label_source = label
        self._state_source = "Not linked"
        self._path: Path | None = None

        self.name_label = QLabel(label)
        self.name_label.setObjectName("ArtifactName")
        self.value_label = QLabel("Not linked")
        self.value_label.setObjectName("ArtifactValue")
        self.state_label = QLabel("Not linked")
        self.state_label.setObjectName("ArtifactState")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setMinimumWidth(62)
        self.relink_button = SvgIconButton("folder", size=28)
        self.relink_button.setObjectName("ModelArtifactButton")
        self.relink_button.setToolTip(tr("Relink {artifact}", artifact=tr(label)))
        self.relink_button.clicked.connect(lambda: self.relink_requested.emit(self._artifact_name))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.value_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(8)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.state_label)
        layout.addWidget(self.relink_button)

    def set_value(self, path: Path | None, state: str) -> None:
        self._path = path
        self._state_source = state
        if path is None:
            value = tr("Not linked")
        elif path.is_dir():
            value = path.name
        else:
            value = path.name
        self.value_label.setText(value)
        self.value_label.setToolTip(str(path) if path is not None else "")
        set_translated_text(self.state_label, state)
        self.state_label.setProperty("state", state.casefold().replace(" ", "_"))
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.relink_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.name_label.setText(tr(self._label_source))
        self.relink_button.setToolTip(tr("Relink {artifact}", artifact=tr(self._label_source)))
        self.set_value(self._path, self._state_source)


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("ModelDetailLabel")
    return label


def _file_state(path: Path | None) -> str:
    if path is None:
        return "Not linked"
    return "Ready" if path.is_file() else "Missing"


def _source_display_path(record: RvcModelRecord) -> str:
    try:
        relative = record.source_folder.resolve().relative_to(record.runtime_root.resolve())
    except ValueError:
        return record.source_folder.name
    return str(relative) if str(relative) != "." else record.runtime_root.name
