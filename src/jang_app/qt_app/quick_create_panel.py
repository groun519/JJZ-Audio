from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
)

from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_text,
)
from jang_app.qt_app.widgets import (
    FeedbackButton,
    ScrollSafeComboBox,
    ScrollSafeSpinBox,
)
from jang_app.services.i18n import tr
from jang_app.services.rvc_model_choices import RvcModelChoice


class QuickCreatePanel(QFrame):
    start_requested = Signal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._has_work_song = False
        self._running = False

        title = QLabel()
        title.setObjectName("CardTitle")
        set_translated_text(title, "Quick Create")

        self.model_combo = ScrollSafeComboBox()
        self.model_combo.setMinimumWidth(0)
        self.model_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)

        self.pitch_spin = ScrollSafeSpinBox()
        self.pitch_spin.setRange(-999, 999)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.addWidget(_field_label("Model"), 0, 0)
        form.addWidget(self.model_combo, 0, 1)
        form.addWidget(_field_label("Pitch"), 1, 0)
        form.addWidget(self.pitch_spin, 1, 1)

        self.action_button = FeedbackButton()
        self.action_button.setObjectName("PrimaryButton")
        self.action_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        set_translated_text(self.action_button, "Start Quick Create")
        self.action_button.clicked.connect(self._emit_start)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ActionProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("ProgressValue")
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label, 0)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(self.action_button)
        layout.addLayout(progress_row)
        layout.addWidget(self.status_label)

        self.set_work_song(can_create=False)
        self.set_model_choices(())

    def selected_model(self) -> RvcModelChoice | None:
        choice = self.model_combo.currentData()
        return choice if isinstance(choice, RvcModelChoice) else None

    def pitch(self) -> int:
        return self.pitch_spin.value()

    def set_work_song(
        self,
        *,
        can_create: bool,
    ) -> None:
        self._has_work_song = bool(can_create)
        if not self._running:
            self.set_progress(0)
            self.set_status("")
        self._sync_enabled_state()

    def set_model_choices(
        self,
        choices: tuple[RvcModelChoice, ...],
        *,
        selected_model_id: str = "",
        selected_model_path: Path | None = None,
        preserve_selection: bool = True,
    ) -> None:
        previous = self.selected_model() if preserve_selection else None
        previous_id = previous.choice_id if previous is not None else ""
        selected_path_key = _path_key(selected_model_path)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem(tr("Select model"), None)
        selected_index = 0
        for choice in choices:
            self.model_combo.addItem(choice.label, choice)
            index = self.model_combo.count() - 1
            self.model_combo.setItemData(
                index,
                str(choice.model_path),
                Qt.ItemDataRole.ToolTipRole,
            )
            if previous_id and choice.choice_id == previous_id:
                selected_index = index
            elif not previous_id and selected_model_id and choice.model_id == selected_model_id:
                selected_index = index
            elif (
                not previous_id
                and not selected_model_id
                and selected_path_key
                and _path_key(choice.model_path) == selected_path_key
            ):
                selected_index = index
        self.model_combo.setCurrentIndex(selected_index)
        self.model_combo.blockSignals(False)
        if previous is None and self.selected_model() is not None:
            self.pitch_spin.setValue(self.selected_model().pitch)
        self._sync_enabled_state()

    def set_running(self, is_running: bool) -> None:
        self._running = bool(is_running)
        self._sync_enabled_state()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_label.setText(f"{progress}%")
        if self._running:
            self.set_status("Separating" if progress < 45 else "Converting")

    def set_status(self, text: str) -> None:
        set_translated_text(self.status_label, text.strip())
        self.status_label.setVisible(bool(text.strip()))

    def apply_language(self) -> None:
        apply_widget_language(self)
        choice = self.selected_model()
        if self.model_combo.count() > 0:
            self.model_combo.setItemText(0, tr("Select model"))
        if choice is not None:
            self.model_combo.setCurrentIndex(
                next(
                    (
                        index
                        for index in range(self.model_combo.count())
                        if self.model_combo.itemData(index) == choice
                    ),
                    0,
                )
            )

    def _on_model_changed(self, _index: int) -> None:
        choice = self.selected_model()
        if choice is not None:
            self.pitch_spin.setValue(choice.pitch)
        self._sync_enabled_state()

    def _emit_start(self) -> None:
        choice = self.selected_model()
        if choice is not None and self._has_work_song and not self._running:
            self.start_requested.emit(choice, self.pitch())

    def _sync_enabled_state(self) -> None:
        has_model = self.selected_model() is not None
        enabled = self._has_work_song and has_model and not self._running
        self.action_button.setEnabled(enabled)
        self.model_combo.setEnabled(not self._running)
        self.pitch_spin.setEnabled(not self._running)


def _field_label(text: str) -> QLabel:
    label = QLabel()
    label.setObjectName("FieldLabel")
    set_translated_text(label, text)
    return label


def _path_key(path: Path | None) -> str:
    if path is None:
        return ""
    return str(path.expanduser().resolve()).casefold()
