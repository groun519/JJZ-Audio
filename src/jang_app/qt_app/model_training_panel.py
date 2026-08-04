from __future__ import annotations

import traceback
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton, ScrollSafeSpinBox
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingState
from jang_app.services.rvc_training_train import RvcTrainingRunSettings


TrainingTask = Callable[[Callable[[int], None], Callable[[str], None]], object]


class ModelTrainingWorker(QThread):
    progress_changed = Signal(int)
    stage_changed = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: TrainingTask) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            result = self._task(self.progress_changed.emit, self.stage_changed.emit)
            self.succeeded.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class ModelTrainingPanel(QWidget):
    start_requested = Signal(object)
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._record: RvcModelRecord | None = None
        self._state: RvcTrainingState | None = None
        self._is_running = False
        self._build_ui()
        self.set_model(None, None, 0, 0)

    def _build_ui(self) -> None:
        summary = QFrame()
        summary.setObjectName("TrainingStatusCard")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(12)

        summary_text = QVBoxLayout()
        summary_text.setContentsMargins(0, 0, 0, 0)
        summary_text.setSpacing(3)
        self.status_label = QLabel("Not Started")
        self.status_label.setObjectName("TrainingStatusTitle")
        self.stage_label = QLabel("Prepare training materials first")
        self.stage_label.setObjectName("TrainingStageText")
        summary_text.addWidget(self.status_label)
        summary_text.addWidget(self.stage_label)

        self.profile_label = QLabel("RVC v2 / 40k / RMVPE")
        self.profile_label.setObjectName("TrainingProfileBadge")
        self.epoch_label = QLabel("0 / 20")
        self.epoch_label.setObjectName("TrainingEpochBadge")
        summary_layout.addLayout(summary_text, 1)
        summary_layout.addWidget(self.profile_label)
        summary_layout.addWidget(self.epoch_label)

        settings = QFrame()
        settings.setObjectName("TrainingSettingsCard")
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setHorizontalSpacing(14)
        settings_layout.setVerticalSpacing(10)

        self.target_epoch_spin = _training_spin(1, 20000, 20)
        self.batch_size_spin = _training_spin(1, 64, 4)
        self.save_interval_spin = _training_spin(1, 20000, 5)
        self.gpu_index_spin = _training_spin(0, 15, 0)
        self.target_epoch_spin.valueChanged.connect(self._sync_interval_limit)

        settings_layout.addWidget(_field_label("Target Epoch"), 0, 0)
        settings_layout.addWidget(_field_label("Batch Size"), 0, 1)
        settings_layout.addWidget(_field_label("Checkpoint Interval"), 0, 2)
        settings_layout.addWidget(_field_label("GPU"), 0, 3)
        settings_layout.addWidget(self.target_epoch_spin, 1, 0)
        settings_layout.addWidget(self.batch_size_spin, 1, 1)
        settings_layout.addWidget(self.save_interval_spin, 1, 2)
        settings_layout.addWidget(self.gpu_index_spin, 1, 3)
        for column in range(4):
            settings_layout.setColumnStretch(column, 1)

        self.start_fresh_check = QCheckBox("Start Fresh")
        self.start_fresh_check.setObjectName("TrainingFreshCheck")
        self.start_fresh_check.toggled.connect(self._sync_action_text)
        settings_layout.addWidget(self.start_fresh_check, 2, 0, 1, 4)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("TrainingProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.start_button = FeedbackButton("Start Training")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._request_start)
        self.stop_button = FeedbackButton("Stop")
        self.stop_button.setObjectName("TrainingStopButton")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.hide()

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addStretch(1)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.start_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(summary)
        layout.addWidget(settings)
        layout.addWidget(self.progress_bar)
        layout.addLayout(action_row)
        layout.addStretch(1)

    def set_model(
        self,
        record: RvcModelRecord | None,
        state: RvcTrainingState | None,
        ready_items: int,
        total_items: int,
    ) -> None:
        self._record = record
        self._state = state
        can_train = record is not None and record.is_managed
        for control in (
            self.target_epoch_spin,
            self.batch_size_spin,
            self.save_interval_spin,
            self.gpu_index_spin,
            self.start_fresh_check,
        ):
            control.setEnabled(can_train and not self._is_running)

        if state is None:
            current_epoch = 0
            target_epoch = 20
            phase = RvcTrainingPhase.IDLE
            can_resume = False
        else:
            current_epoch = state.current_epoch
            target_epoch = state.target_epoch
            phase = state.phase
            can_resume = state.can_resume

        minimum_target = max(1, current_epoch + 1)
        suggested_target = max(target_epoch, minimum_target)
        if current_epoch and suggested_target <= current_epoch:
            suggested_target = current_epoch + 20
        self.target_epoch_spin.setMinimum(minimum_target)
        self.target_epoch_spin.setValue(suggested_target)
        self.start_fresh_check.setVisible(can_resume)
        if not can_resume:
            self.start_fresh_check.setChecked(False)

        self.epoch_label.setText(f"{current_epoch} / {self.target_epoch_spin.value()}")
        self.status_label.setProperty("phase", phase.value)
        set_translated_text(self.status_label, _phase_label(phase))
        if record is None:
            set_translated_text(self.stage_label, "Select a model")
        elif not record.is_managed:
            set_translated_text(self.stage_label, "Import a managed copy to train")
        elif total_items == 0:
            set_translated_text(self.stage_label, "Prepare training materials first")
        else:
            set_translated_text(
                self.stage_label,
                "{ready} of {total} materials ready",
                ready=ready_items,
                total=total_items,
            )
        self._refresh_status_style()
        self._sync_action_text()
        self._sync_enabled_state()

    def set_running(self, is_running: bool) -> None:
        self._is_running = is_running
        self.start_button.setVisible(not is_running)
        self.stop_button.setVisible(is_running)
        self.progress_bar.setProperty("running", is_running)
        self._sync_enabled_state()
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

    def set_progress(self, value: int) -> None:
        self.progress_bar.setValue(max(0, min(100, int(value))))

    def set_stage(self, text: str) -> None:
        set_translated_text(self.stage_label, text)

    def set_failure(self, error: str) -> None:
        set_translated_text(self.status_label, "Failed")
        self.status_label.setProperty("phase", RvcTrainingPhase.FAILED.value)
        self.stage_label.setText(_last_error_line(error))
        self.stage_label.setToolTip(error)
        self._refresh_status_style()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._sync_action_text()

    def _request_start(self) -> None:
        self.start_requested.emit(
            RvcTrainingRunSettings(
                target_epoch=self.target_epoch_spin.value(),
                batch_size=self.batch_size_spin.value(),
                save_every_epoch=self.save_interval_spin.value(),
                gpu_index=self.gpu_index_spin.value(),
                resume=not self.start_fresh_check.isChecked(),
            )
        )

    def _sync_interval_limit(self, target_epoch: int) -> None:
        self.save_interval_spin.setMaximum(max(1, target_epoch))
        self.epoch_label.setText(
            f"{self._state.current_epoch if self._state is not None else 0} / {target_epoch}"
        )

    def _sync_action_text(self) -> None:
        can_resume = self._state is not None and self._state.can_resume
        action = "Resume Training" if can_resume and not self.start_fresh_check.isChecked() else "Start Training"
        set_translated_text(self.start_button, action)

    def _sync_enabled_state(self) -> None:
        can_train = self._record is not None and self._record.is_managed
        settings_enabled = can_train and not self._is_running
        for control in (
            self.target_epoch_spin,
            self.batch_size_spin,
            self.save_interval_spin,
            self.gpu_index_spin,
            self.start_fresh_check,
        ):
            control.setEnabled(settings_enabled)
        self.start_button.setEnabled(can_train and not self._is_running)
        self.stop_button.setEnabled(self._is_running)

    def _refresh_status_style(self) -> None:
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


def _training_spin(minimum: int, maximum: int, value: int) -> ScrollSafeSpinBox:
    spin = ScrollSafeSpinBox()
    spin.setObjectName("TrainingSpinBox")
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("TrainingFieldLabel")
    return label


def _phase_label(phase: RvcTrainingPhase) -> str:
    return {
        RvcTrainingPhase.IDLE: "Not Started",
        RvcTrainingPhase.PREPROCESS: "Preparing Audio",
        RvcTrainingPhase.PREPROCESSED: "Audio Prepared",
        RvcTrainingPhase.EXTRACT: "Extracting Features",
        RvcTrainingPhase.FEATURES_READY: "Features Ready",
        RvcTrainingPhase.FILELIST_READY: "Ready to Train",
        RvcTrainingPhase.TRAIN: "Training",
        RvcTrainingPhase.STOPPED: "Stopped",
        RvcTrainingPhase.INDEX: "Building Index",
        RvcTrainingPhase.INDEX_READY: "Index Ready",
        RvcTrainingPhase.COMPLETE: "Complete",
        RvcTrainingPhase.FAILED: "Failed",
    }[phase]


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Training failed"
