from __future__ import annotations

import traceback
from collections.abc import Callable
from time import monotonic

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import (
    FeedbackButton,
    InfoPopoverButton,
    ScrollSafeSpinBox,
    configure_two_line_status_text,
)
from jang_app.qt_app.workflow_progress import WorkflowProgress, WorkflowStage
from jang_app.services.audio_metadata import format_duration
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import diagnostic_task
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_presets import (
    TRAINING_PRESETS,
    RvcTrainingPresetId,
    recommend_rvc_training_settings,
)
from jang_app.services.rvc_training_preflight import (
    RvcTrainingPreflight,
    basic_rvc_training_preflight,
)
from jang_app.services.rvc_training_preprocess import RvcTrainingPreprocessFailure
from jang_app.services.rvc_training_recovery import (
    RvcTrainingRecoveryAction,
    RvcTrainingRecoveryAdvice,
    advise_rvc_training_recovery,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingState
from jang_app.services.rvc_training_train import RvcTrainingRunSettings


TrainingTask = Callable[
    [
        Callable[[int], None],
        Callable[[str], None],
        Callable[[int, int], None],
        Callable[[], None],
        Callable[[object], None],
    ],
    object,
]


class ModelTrainingWorker(QThread):
    progress_changed = Signal(int)
    stage_changed = Signal(str)
    epoch_changed = Signal(int, int)
    activity_changed = Signal()
    preprocess_changed = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: TrainingTask) -> None:
        super().__init__()
        self._task = task
        self._last_activity_emit = 0.0
        self._diagnostic_task_id = ""

    def set_diagnostic_task_id(self, task_id: str) -> None:
        self._diagnostic_task_id = task_id

    def run(self) -> None:
        with diagnostic_task(self._diagnostic_task_id):
            try:
                result = self._task(
                    self.progress_changed.emit,
                    self.stage_changed.emit,
                    self.epoch_changed.emit,
                    self._emit_activity,
                    self.preprocess_changed.emit,
                )
                self.succeeded.emit(result)
            except Exception:
                self.failed.emit(traceback.format_exc())

    def _emit_activity(self) -> None:
        now = monotonic()
        if now - self._last_activity_emit < 0.5:
            return
        self._last_activity_emit = now
        self.activity_changed.emit()


class ModelTrainingPanel(QWidget):
    start_requested = Signal(object)
    stop_requested = Signal()
    diagnostics_requested = Signal(str)
    system_setup_requested = Signal()
    preflight_requested = Signal()
    excluded_clip_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._record: RvcModelRecord | None = None
        self._state: RvcTrainingState | None = None
        self._is_running = False
        self._training_accelerated = True
        self._inference_backend = RvcComputeBackend.CUDA
        self._training_backend = RvcComputeBackend.CUDA
        self._adapter_name = ""
        self._adapter_memory_bytes = 0
        self._ready_items = 0
        self._total_items = 0
        self._preflight = basic_rvc_training_preflight(
            managed_model=False,
            ready_items=0,
            total_items=0,
        )
        self._recovery_advice: RvcTrainingRecoveryAdvice | None = None
        self._recovery_task_id = ""
        self._active_stage_key = ""
        self._current_epoch = 0
        self._target_epoch = 20
        self._last_epoch_at = 0.0
        self._seconds_per_epoch = 0.0
        self._active_preset = RvcTrainingPresetId.QUICK
        self._applying_preset = False
        self._preprocess_total_inputs = 0
        self._preprocess_used_inputs = 0
        self._preprocess_failures: tuple[RvcTrainingPreprocessFailure, ...] = ()
        self._build_ui()
        self.set_model(None, None, 0, 0)

    def _build_ui(self) -> None:
        summary = QFrame()
        summary.setObjectName("TrainingStatusCard")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(18, 16, 18, 16)
        summary_layout.setSpacing(16)

        summary_header = QHBoxLayout()
        summary_header.setContentsMargins(0, 0, 0, 0)
        summary_header.setSpacing(12)
        summary_text = QVBoxLayout()
        summary_text.setContentsMargins(0, 0, 0, 0)
        summary_text.setSpacing(4)
        self.status_label = QLabel("Not Started")
        self.status_label.setObjectName("TrainingStatusTitle")
        self.stage_label = QLabel("Prepare training materials first")
        self.stage_label.setObjectName("TrainingStageText")
        self.stage_label.setWordWrap(True)
        summary_text.addWidget(self.status_label)
        summary_text.addWidget(self.stage_label)

        self.profile_label = QLabel("RVC v2 / 40k / RMVPE / CUDA")
        self.profile_label.setObjectName("TrainingProfileBadge")
        self.conversion_device_label = QLabel("Conversion: CUDA GPU")
        self.conversion_device_label.setObjectName("TrainingComputeBadge")
        self.training_device_label = QLabel("Training: CUDA GPU")
        self.training_device_label.setObjectName("TrainingComputeBadge")
        self.epoch_label = QLabel("0 / 20")
        self.epoch_label.setObjectName("TrainingEpochBadge")
        summary_header.addLayout(summary_text, 1)
        summary_header.addWidget(self.profile_label)
        summary_header.addWidget(self.conversion_device_label)
        summary_header.addWidget(self.training_device_label)
        summary_header.addWidget(self.epoch_label)
        summary_layout.addLayout(summary_header)

        self.workflow_progress = WorkflowProgress(
            (
                WorkflowStage("data", "Data"),
                WorkflowStage("prepare", "Prepare"),
                WorkflowStage("features", "Features"),
                WorkflowStage("train", "Train"),
                WorkflowStage("index", "Index"),
            )
        )
        self.workflow_progress.setObjectName("TrainingWorkflow")
        summary_layout.addWidget(self.workflow_progress)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("TrainingProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("TrainingProgressText")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_percent_label)
        summary_layout.addLayout(progress_row)

        self.activity_label = QLabel("Working")
        self.activity_label.setObjectName("TrainingActivityText")
        self.runtime_label = QLabel("Elapsed 00:00")
        self.runtime_label.setObjectName("TrainingRuntimeText")
        self.remaining_label = QLabel("Estimating remaining time")
        self.remaining_label.setObjectName("TrainingRuntimeText")

        self.runtime_row = QWidget()
        runtime_layout = QHBoxLayout(self.runtime_row)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        runtime_layout.setSpacing(10)
        runtime_layout.addWidget(self.activity_label)
        runtime_layout.addStretch(1)
        runtime_layout.addWidget(self.remaining_label)
        runtime_layout.addWidget(self.runtime_label)
        self.runtime_row.hide()
        summary_layout.addWidget(self.runtime_row)

        self.preprocess_notice_card = QFrame()
        self.preprocess_notice_card.setObjectName("TrainingInputNotice")
        preprocess_notice_layout = QVBoxLayout(self.preprocess_notice_card)
        preprocess_notice_layout.setContentsMargins(16, 14, 16, 14)
        preprocess_notice_layout.setSpacing(9)

        preprocess_notice_header = QHBoxLayout()
        preprocess_notice_header.setContentsMargins(0, 0, 0, 0)
        preprocess_notice_header.setSpacing(10)
        self.preprocess_notice_title = QLabel()
        self.preprocess_notice_title.setObjectName("TrainingInputNoticeTitle")
        self.preprocess_notice_badge = QLabel()
        self.preprocess_notice_badge.setObjectName("TrainingInputNoticeBadge")
        self.preprocess_notice_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preprocess_notice_header.addWidget(self.preprocess_notice_title)
        preprocess_notice_header.addStretch(1)
        preprocess_notice_header.addWidget(self.preprocess_notice_badge)
        preprocess_notice_layout.addLayout(preprocess_notice_header)

        self.preprocess_notice_detail = QLabel()
        self.preprocess_notice_detail.setObjectName("TrainingInputNoticeDetail")
        self.preprocess_notice_detail.setWordWrap(True)
        preprocess_notice_layout.addWidget(self.preprocess_notice_detail)

        preprocess_notice_actions = QHBoxLayout()
        preprocess_notice_actions.setContentsMargins(0, 0, 0, 0)
        preprocess_notice_actions.setSpacing(8)
        self.excluded_clip_combo = QComboBox()
        self.excluded_clip_combo.setObjectName("TrainingExcludedClipCombo")
        self.excluded_clip_button = FeedbackButton("Review Clip")
        self.excluded_clip_button.setObjectName("TrainingExcludedClipButton")
        self.excluded_clip_button.clicked.connect(self._request_excluded_clip)
        preprocess_notice_actions.addWidget(self.excluded_clip_combo, 1)
        preprocess_notice_actions.addWidget(self.excluded_clip_button)
        preprocess_notice_layout.addLayout(preprocess_notice_actions)
        self.preprocess_notice_card.hide()

        self.recovery_card = QFrame()
        self.recovery_card.setObjectName("TrainingRecoveryCard")
        recovery_layout = QVBoxLayout(self.recovery_card)
        recovery_layout.setContentsMargins(16, 14, 16, 14)
        recovery_layout.setSpacing(9)

        recovery_header = QHBoxLayout()
        recovery_header.setContentsMargins(0, 0, 0, 0)
        recovery_header.setSpacing(10)
        recovery_label = QLabel("Recovery")
        recovery_label.setObjectName("TrainingCardTitle")
        self.recovery_code_label = QLabel()
        self.recovery_code_label.setObjectName("TrainingRecoveryCode")
        recovery_header.addWidget(recovery_label)
        recovery_header.addStretch(1)
        recovery_header.addWidget(self.recovery_code_label)
        recovery_layout.addLayout(recovery_header)

        self.recovery_title_label = QLabel()
        self.recovery_title_label.setObjectName("TrainingRecoveryTitle")
        self.recovery_detail_label = QLabel()
        self.recovery_detail_label.setObjectName("TrainingRecoveryDetail")
        self.recovery_detail_label.setWordWrap(True)
        recovery_layout.addWidget(self.recovery_title_label)
        recovery_layout.addWidget(self.recovery_detail_label)

        recovery_actions = QHBoxLayout()
        recovery_actions.setContentsMargins(0, 0, 0, 0)
        recovery_actions.setSpacing(8)
        recovery_actions.addStretch(1)
        self.recovery_diagnostics_button = FeedbackButton("View Diagnostics")
        self.recovery_diagnostics_button.setObjectName("TrainingRecoverySecondaryButton")
        self.recovery_diagnostics_button.clicked.connect(
            lambda: self.diagnostics_requested.emit(self._recovery_task_id)
        )
        self.recovery_primary_button = FeedbackButton("Retry Training")
        self.recovery_primary_button.setObjectName("PrimaryButton")
        self.recovery_primary_button.clicked.connect(self._run_recovery_action)
        recovery_actions.addWidget(self.recovery_diagnostics_button)
        recovery_actions.addWidget(self.recovery_primary_button)
        recovery_layout.addLayout(recovery_actions)
        self.recovery_card.hide()

        readiness = QFrame()
        readiness.setObjectName("TrainingReadinessCard")
        readiness_layout = QVBoxLayout(readiness)
        readiness_layout.setContentsMargins(16, 14, 16, 14)
        readiness_layout.setSpacing(12)

        readiness_header = QHBoxLayout()
        readiness_header.setContentsMargins(0, 0, 0, 0)
        readiness_title = QLabel("Training Preflight")
        readiness_title.setObjectName("TrainingCardTitle")
        self.readiness_badge = QLabel("Not Ready")
        self.readiness_badge.setObjectName("TrainingReadinessBadge")
        readiness_header.addWidget(readiness_title)
        readiness_header.addStretch(1)
        readiness_header.addWidget(self.readiness_badge)
        readiness_layout.addLayout(readiness_header)

        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(10)
        material_metric, self.material_value = _training_metric("Materials")
        duration_metric, self.duration_value = _training_metric("Duration")
        checkpoint_metric, self.checkpoint_value = _training_metric("Checkpoint")
        metrics.addWidget(material_metric, 1)
        metrics.addWidget(duration_metric, 1)
        metrics.addWidget(checkpoint_metric, 1)
        readiness_layout.addLayout(metrics)

        checks = QGridLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        checks.setHorizontalSpacing(10)
        checks.setVerticalSpacing(8)
        self.preflight_rows: dict[str, tuple[QFrame, QLabel, QLabel]] = {}
        for index, key in enumerate(
            ("model", "materials", "analysis", "runtime", "storage", "device")
        ):
            frame, title, detail = _training_preflight_check()
            self.preflight_rows[key] = (frame, title, detail)
            checks.addWidget(frame, index // 2, index % 2)
        checks.setColumnStretch(0, 1)
        checks.setColumnStretch(1, 1)
        readiness_layout.addLayout(checks)

        settings = QFrame()
        settings.setObjectName("TrainingSettingsCard")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(14)

        settings_header = QHBoxLayout()
        settings_header.setContentsMargins(0, 0, 0, 0)
        settings_title = QLabel("Training Settings")
        settings_title.setObjectName("TrainingCardTitle")
        settings_header.addWidget(settings_title)
        settings_header.addStretch(1)

        self.mode_control = QFrame()
        self.mode_control.setObjectName("TrainingModeControl")
        mode_layout = QHBoxLayout(self.mode_control)
        mode_layout.setContentsMargins(3, 3, 3, 3)
        mode_layout.setSpacing(3)
        self.resume_mode_button = FeedbackButton("Resume")
        self.fresh_mode_button = FeedbackButton("Start Over")
        for button in (self.resume_mode_button, self.fresh_mode_button):
            button.setObjectName("TrainingModeButton")
            button.setCheckable(True)
            mode_layout.addWidget(button)
        self.resume_mode_button.setChecked(True)
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.mode_button_group.addButton(self.resume_mode_button)
        self.mode_button_group.addButton(self.fresh_mode_button)
        self.mode_control.hide()
        settings_header.addWidget(self.mode_control)
        settings_layout.addLayout(settings_header)

        self.preset_control = QFrame()
        self.preset_control.setObjectName("TrainingPresetControl")
        preset_layout = QHBoxLayout(self.preset_control)
        preset_layout.setContentsMargins(3, 3, 3, 3)
        preset_layout.setSpacing(3)
        self.preset_button_group = QButtonGroup(self)
        self.preset_button_group.setExclusive(True)
        self.preset_buttons: dict[RvcTrainingPresetId, FeedbackButton] = {}
        preset_labels = {
            preset_id: preset.label
            for preset_id, preset in TRAINING_PRESETS.items()
        }
        preset_labels[RvcTrainingPresetId.CUSTOM] = "Custom"
        for preset_id in RvcTrainingPresetId:
            button = FeedbackButton(preset_labels[preset_id])
            button.setObjectName("TrainingPresetButton")
            button.setProperty("presetId", preset_id.value)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, selected=preset_id: self._select_preset(selected)
            )
            self.preset_button_group.addButton(button)
            self.preset_buttons[preset_id] = button
            preset_layout.addWidget(button, 1)
        self.preset_buttons[self._active_preset].setChecked(True)
        settings_layout.addWidget(self.preset_control)

        self.preset_summary_label = QLabel()
        self.preset_summary_label.setObjectName("TrainingPresetSummary")
        self.preset_summary_label.setWordWrap(True)
        settings_layout.addWidget(self.preset_summary_label)

        fields = QGridLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(10)

        self.target_epoch_spin = _training_spin(1, 20000, 20)
        self.batch_size_spin = _training_spin(1, 64, 4)
        self.save_interval_spin = _training_spin(1, 20000, 5)
        self.gpu_index_spin = _training_spin(0, 15, 0)
        self.target_epoch_spin.valueChanged.connect(self._sync_interval_limit)
        self.target_epoch_spin.valueChanged.connect(self._mark_custom_settings)
        self.batch_size_spin.valueChanged.connect(self._mark_custom_settings)
        self.save_interval_spin.valueChanged.connect(self._mark_custom_settings)
        self.resume_mode_button.toggled.connect(self._sync_training_mode)
        self.fresh_mode_button.toggled.connect(self._sync_training_mode)

        self.target_epoch_info = InfoPopoverButton()
        self.batch_size_info = InfoPopoverButton()
        self.checkpoint_interval_info = InfoPopoverButton()
        self.training_device_info = InfoPopoverButton()
        target_header, _target_label = _field_label_with_info(
            "Target Epoch",
            self.target_epoch_info,
        )
        batch_header, _batch_label = _field_label_with_info(
            "Batch Size",
            self.batch_size_info,
        )
        checkpoint_header, _checkpoint_label = _field_label_with_info(
            "Checkpoint Interval",
            self.checkpoint_interval_info,
        )
        device_header, self.device_field_label = _field_label_with_info(
            "GPU",
            self.training_device_info,
        )
        fields.addWidget(target_header, 0, 0)
        fields.addWidget(batch_header, 0, 1)
        fields.addWidget(checkpoint_header, 0, 2)
        self.cpu_device_label = QLabel("CPU")
        self.cpu_device_label.setObjectName("TrainingDeviceValue")
        self.device_stack = QStackedWidget()
        self.device_stack.setObjectName("TrainingDeviceStack")
        self.device_stack.addWidget(self.gpu_index_spin)
        self.device_stack.addWidget(self.cpu_device_label)

        fields.addWidget(device_header, 0, 3)
        fields.addWidget(self.target_epoch_spin, 1, 0)
        fields.addWidget(self.batch_size_spin, 1, 1)
        fields.addWidget(self.save_interval_spin, 1, 2)
        fields.addWidget(self.device_stack, 1, 3)
        for column in range(4):
            fields.setColumnStretch(column, 1)
        settings_layout.addLayout(fields)

        self.start_button = FeedbackButton("Start Training")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._request_start)
        self.stop_button = FeedbackButton("Stop")
        self.stop_button.setObjectName("TrainingStopButton")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.hide()

        self.start_hint_label = QLabel("Prepare training materials first")
        self.start_hint_label.setObjectName("TrainingStartHint")
        self.start_hint_label.setWordWrap(True)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.start_hint_label, 1)
        action_row.addStretch(1)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.start_button)
        settings_layout.addLayout(action_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(summary)
        layout.addWidget(self.preprocess_notice_card)
        layout.addWidget(self.recovery_card)
        layout.addWidget(readiness)
        layout.addWidget(settings)
        layout.addStretch(1)
        self._sync_preset_summary()
        self._sync_info_popovers()

    def set_model(
        self,
        record: RvcModelRecord | None,
        state: RvcTrainingState | None,
        ready_items: int,
        total_items: int,
        total_duration_ms: int = 0,
        preflight: RvcTrainingPreflight | None = None,
    ) -> None:
        previous_model_id = self._record.model_id if self._record is not None else ""
        self._record = record
        self._state = state
        self._ready_items = max(0, int(ready_items))
        self._total_items = max(0, int(total_items))
        current_model_id = record.model_id if record is not None else ""
        if current_model_id != previous_model_id:
            self.clear_preprocess_summary()
        can_train = record is not None and record.is_managed
        self._preflight = preflight or basic_rvc_training_preflight(
            managed_model=can_train,
            ready_items=self._ready_items,
            total_items=self._total_items,
        )
        for control in (
            self.target_epoch_spin,
            self.batch_size_spin,
            self.save_interval_spin,
            self.gpu_index_spin,
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

        self._current_epoch = current_epoch
        self._target_epoch = target_epoch
        self.mode_control.setVisible(can_resume)
        if not can_resume or (
            record is not None and record.model_id != previous_model_id
        ):
            self.resume_mode_button.setChecked(True)
        minimum_target = current_epoch + 1 if can_resume and self.resume_mode_button.isChecked() else 1
        suggested_target = max(target_epoch, minimum_target)
        if can_resume and self.resume_mode_button.isChecked() and target_epoch <= current_epoch:
            suggested_target = current_epoch + 20
        self._applying_preset = True
        try:
            self.target_epoch_spin.setMinimum(minimum_target)
            self.target_epoch_spin.setValue(suggested_target)
        finally:
            self._applying_preset = False
        self._sync_preset_from_settings()
        self._sync_epoch_label()

        self.material_value.setText(f"{self._ready_items} / {self._total_items}")
        self.duration_value.setText(
            format_duration(max(0, int(total_duration_ms))) if total_duration_ms else "--:--"
        )
        if can_resume:
            if current_epoch > 0:
                set_translated_text(
                    self.checkpoint_value,
                    "Epoch {epoch}",
                    epoch=current_epoch,
                )
            else:
                set_translated_text(
                    self.checkpoint_value,
                    "Step {step}",
                    step=state.checkpoint_step if state is not None else 0,
                )
        else:
            set_translated_text(self.checkpoint_value, "None")
        self._sync_preflight()

        self.status_label.setProperty("phase", phase.value)
        set_translated_text(self.status_label, _phase_label(phase))
        self.stage_label.setToolTip("")
        if record is None:
            set_translated_text(self.stage_label, "Select a model")
        elif not record.is_managed:
            set_translated_text(self.stage_label, "Import a managed copy to train")
        elif self._total_items == 0:
            set_translated_text(self.stage_label, "Prepare training materials first")
        elif self._ready_items < self._total_items:
            set_translated_text(
                self.stage_label,
                "{ready} of {total} materials ready",
                ready=self._ready_items,
                total=self._total_items,
            )
        elif self._preflight.blockers:
            blocker = self._preflight.blockers[0]
            set_translated_text(
                self.stage_label,
                blocker.detail,
                **blocker.format_values,
            )
        elif phase == RvcTrainingPhase.COMPLETE:
            set_translated_text(self.stage_label, "Model and index are ready")
        elif phase == RvcTrainingPhase.STOPPED and can_resume:
            set_translated_text(
                self.stage_label,
                "Checkpoint available at epoch {epoch}",
                epoch=current_epoch,
            )
        elif phase == RvcTrainingPhase.FAILED and state is not None and state.last_error:
            self.stage_label.setText(_last_error_line(state.last_error))
            self.stage_label.setToolTip(state.last_error)
        else:
            set_translated_text(self.stage_label, "Ready to train")
        if phase == RvcTrainingPhase.FAILED and state is not None and state.last_error:
            self._set_recovery(
                state.last_error,
                task_id=state.last_task_id,
                diagnostic_code=state.last_diagnostic_code,
            )
        else:
            self._clear_recovery()
        self._sync_workflow_for_phase(phase)
        self._refresh_status_style()
        self._sync_action_text()
        self._sync_enabled_state()

    def set_running(self, is_running: bool) -> None:
        self._is_running = is_running
        if is_running:
            self._last_epoch_at = 0.0
            self._seconds_per_epoch = 0.0
            self.status_label.setProperty("phase", RvcTrainingPhase.TRAIN.value)
            set_translated_text(self.status_label, "Training")
            self.stage_label.setToolTip("")
            self._active_stage_key = "data"
            self.workflow_progress.set_status("data")
            self._refresh_status_style()
        self._sync_recovery_visibility()
        self.stop_button.setVisible(is_running)
        self.start_hint_label.setVisible(not is_running)
        self.runtime_row.setVisible(is_running)
        self.progress_bar.setProperty("running", is_running)
        self._sync_enabled_state()
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

    def set_compute_backends(
        self,
        inference_backend: RvcComputeBackend,
        training_backend: RvcComputeBackend,
        *,
        adapter_name: str = "",
        adapter_memory_bytes: int = 0,
    ) -> None:
        self._inference_backend = inference_backend
        self._training_backend = training_backend
        self._adapter_name = adapter_name.strip()
        self._adapter_memory_bytes = max(0, int(adapter_memory_bytes))
        self._training_accelerated = training_backend in {
            RvcComputeBackend.CUDA,
            RvcComputeBackend.ROCM,
        }
        set_translated_text(
            self.profile_label,
            "RVC v2 / 40k / RMVPE",
        )
        conversion_label = {
            RvcComputeBackend.CUDA: "CUDA GPU",
            RvcComputeBackend.ROCM: "ROCm GPU",
            RvcComputeBackend.DIRECTML: "DirectML GPU",
            RvcComputeBackend.CPU: "CPU",
        }[inference_backend]
        training_label = {
            RvcComputeBackend.CUDA: "CUDA GPU",
            RvcComputeBackend.ROCM: "ROCm GPU",
            RvcComputeBackend.DIRECTML: "DirectML GPU",
            RvcComputeBackend.CPU: "CPU",
        }[training_backend]
        set_translated_text(
            self.conversion_device_label,
            "Conversion: {device}",
            device=tr(conversion_label),
        )
        set_translated_text(
            self.training_device_label,
            "Training: {device}",
            device=tr(training_label),
        )
        if self._training_accelerated:
            set_translated_text(self.device_field_label, "GPU")
            self.device_stack.setCurrentWidget(self.gpu_index_spin)
        else:
            set_translated_text(self.device_field_label, "Training Device")
            self.cpu_device_label.setText(tr("CPU"))
            self.device_stack.setCurrentWidget(self.cpu_device_label)
        if self._active_preset != RvcTrainingPresetId.CUSTOM:
            self._apply_preset(self._active_preset)
        else:
            self._sync_info_popovers()
        self._sync_enabled_state()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_percent_label.setText(f"{progress}%")

    def set_preprocess_summary(
        self,
        total_inputs: int,
        successful_inputs: int,
        failed_inputs: tuple[RvcTrainingPreprocessFailure, ...],
    ) -> None:
        self._preprocess_total_inputs = max(0, int(total_inputs))
        self._preprocess_used_inputs = max(0, int(successful_inputs))
        self._preprocess_failures = tuple(failed_inputs)
        self.excluded_clip_combo.clear()
        for failure in self._preprocess_failures:
            self.excluded_clip_combo.addItem(failure.input_name, failure)
            index = self.excluded_clip_combo.count() - 1
            self.excluded_clip_combo.setItemData(
                index,
                failure.reason,
                Qt.ItemDataRole.ToolTipRole,
            )
        self._sync_preprocess_summary()

    def clear_preprocess_summary(self) -> None:
        self._preprocess_total_inputs = 0
        self._preprocess_used_inputs = 0
        self._preprocess_failures = ()
        self.excluded_clip_combo.clear()
        self.preprocess_notice_card.hide()

    def set_epoch_progress(self, current_epoch: int, target_epoch: int) -> None:
        current = max(0, int(current_epoch))
        target = max(1, int(target_epoch))
        now = monotonic()
        if self._is_running:
            if self._last_epoch_at > 0 and current > self._current_epoch:
                sample = (now - self._last_epoch_at) / (current - self._current_epoch)
                if sample > 0:
                    self._seconds_per_epoch = (
                        sample
                        if self._seconds_per_epoch <= 0
                        else self._seconds_per_epoch * 0.7 + sample * 0.3
                    )
            if current != self._current_epoch or self._last_epoch_at <= 0:
                self._last_epoch_at = now
        self._current_epoch = current
        self._target_epoch = target
        self.epoch_label.setText(f"{current} / {target}")

    def set_stage(self, text: str) -> None:
        set_translated_text(self.stage_label, text)
        stage_key = _workflow_key_for_stage(text)
        if stage_key:
            self._active_stage_key = stage_key
            self.workflow_progress.set_status(
                stage_key,
                completed_keys=_completed_workflow_stages(stage_key),
            )

    def set_runtime_status(self, elapsed_seconds: int, idle_seconds: int) -> None:
        elapsed = max(0, int(elapsed_seconds))
        idle = max(0, int(idle_seconds))
        dots = "." * (elapsed % 3 + 1)
        self.activity_label.setText(f"{tr('Working')}{dots}")
        elapsed_text = tr("Elapsed {elapsed}", elapsed=format_training_elapsed(elapsed))
        if idle < 2:
            activity_text = tr("Active now")
        else:
            activity_text = tr(
                "Last activity {idle} ago",
                idle=format_training_elapsed(idle),
            )
        self.runtime_label.setText(f"{elapsed_text}  |  {activity_text}")
        remaining_epochs = max(0, self._target_epoch - self._current_epoch)
        if self._seconds_per_epoch > 0 and remaining_epochs > 0:
            remaining = format_training_elapsed(
                round(self._seconds_per_epoch * remaining_epochs)
            )
            set_translated_text(
                self.remaining_label,
                "About {remaining} remaining",
                remaining=remaining,
            )
        elif remaining_epochs == 0 and self._active_stage_key in {"train", "index"}:
            set_translated_text(self.remaining_label, "Finishing")
        else:
            set_translated_text(self.remaining_label, "Estimating remaining time")

    def set_failure(
        self,
        error: str,
        *,
        task_id: str = "",
        diagnostic_code: str = "",
    ) -> None:
        set_translated_text(self.status_label, "Failed")
        self.status_label.setProperty("phase", RvcTrainingPhase.FAILED.value)
        self.stage_label.setText(_last_error_line(error))
        self.stage_label.setToolTip(error)
        self._set_recovery(
            error,
            task_id=task_id,
            diagnostic_code=diagnostic_code,
        )
        failed_stage = self._active_stage_key or "data"
        self.workflow_progress.set_status(
            failed_stage,
            completed_keys=_completed_workflow_stages(failed_stage),
            failed=True,
        )
        self._refresh_status_style()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._sync_action_text()
        self._sync_preset_summary()
        self._sync_info_popovers()
        self._sync_preflight()
        self._sync_recovery()
        self._sync_preprocess_summary()

    def _request_excluded_clip(self) -> None:
        failure = self.excluded_clip_combo.currentData()
        if isinstance(failure, RvcTrainingPreprocessFailure):
            self.excluded_clip_requested.emit(failure)

    def _sync_preprocess_summary(self) -> None:
        excluded = len(self._preprocess_failures)
        self.preprocess_notice_card.setVisible(excluded > 0)
        if not excluded:
            return
        set_translated_text(
            self.preprocess_notice_title,
            "Some Clips Were Excluded",
        )
        set_translated_text(
            self.preprocess_notice_detail,
            (
                "{used} of {total} clips will be used for training. "
                "The {excluded} excluded clips will not affect this model."
            ),
            used=self._preprocess_used_inputs,
            total=self._preprocess_total_inputs,
            excluded=excluded,
        )
        set_translated_text(
            self.preprocess_notice_badge,
            "Excluded {count}",
            count=excluded,
        )
        set_translated_text(self.excluded_clip_button, "Review Clip")
        self.excluded_clip_button.setEnabled(
            isinstance(self.excluded_clip_combo.currentData(), RvcTrainingPreprocessFailure)
        )

    def _request_start(self) -> None:
        self.start_requested.emit(
            RvcTrainingRunSettings(
                target_epoch=self.target_epoch_spin.value(),
                batch_size=self.batch_size_spin.value(),
                save_every_epoch=self.save_interval_spin.value(),
                gpu_index=self.gpu_index_spin.value(),
                resume=(
                    self._state is not None
                    and self._state.can_resume
                    and self.resume_mode_button.isChecked()
                ),
            )
        )

    def _set_recovery(
        self,
        error: str,
        *,
        task_id: str = "",
        diagnostic_code: str = "",
    ) -> None:
        self._recovery_advice = advise_rvc_training_recovery(
            error,
            can_resume=self._state is not None and self._state.can_resume,
            current_batch_size=self.batch_size_spin.value(),
            diagnostic_code=diagnostic_code,
        )
        self._recovery_task_id = task_id.strip()
        self._sync_recovery()
        self._sync_recovery_visibility()
        self._sync_enabled_state()

    def _clear_recovery(self) -> None:
        self._recovery_advice = None
        self._recovery_task_id = ""
        self._sync_recovery_visibility()

    def _sync_recovery(self) -> None:
        advice = self._recovery_advice
        if advice is None:
            return
        self.recovery_code_label.setText(advice.diagnostic_code)
        set_translated_text(self.recovery_title_label, advice.title)
        set_translated_text(
            self.recovery_detail_label,
            advice.detail,
            batch=advice.suggested_batch_size,
        )
        action_text = {
            RvcTrainingRecoveryAction.RETRY: "Retry Training",
            RvcTrainingRecoveryAction.RESUME: "Resume from Checkpoint",
            RvcTrainingRecoveryAction.RETRY_SAFE_BATCH: "Retry with Batch {batch}",
            RvcTrainingRecoveryAction.OPEN_SYSTEM_SETUP: "Open System Setup",
            RvcTrainingRecoveryAction.RECHECK: "Run Preflight Again",
        }[advice.action]
        set_translated_text(
            self.recovery_primary_button,
            action_text,
            batch=advice.suggested_batch_size,
        )
        set_translated_text(self.recovery_diagnostics_button, "View Diagnostics")

    def _sync_recovery_visibility(self) -> None:
        recovery_visible = self._recovery_advice is not None and not self._is_running
        recovery_owns_start = (
            self._recovery_advice is not None
            and self._recovery_advice.action
            in {
                RvcTrainingRecoveryAction.RETRY,
                RvcTrainingRecoveryAction.RESUME,
                RvcTrainingRecoveryAction.RETRY_SAFE_BATCH,
            }
        )
        self.recovery_card.setVisible(recovery_visible)
        self.start_button.setVisible(
            not self._is_running and not (recovery_visible and recovery_owns_start)
        )
        if recovery_visible:
            self.start_hint_label.hide()

    def _run_recovery_action(self) -> None:
        advice = self._recovery_advice
        if advice is None:
            return
        if advice.action == RvcTrainingRecoveryAction.OPEN_SYSTEM_SETUP:
            self.system_setup_requested.emit()
            return
        if advice.action == RvcTrainingRecoveryAction.RECHECK:
            self.preflight_requested.emit()
            return
        if advice.action == RvcTrainingRecoveryAction.RETRY_SAFE_BATCH:
            self.batch_size_spin.setValue(advice.suggested_batch_size)
        if (
            advice.action
            in {
                RvcTrainingRecoveryAction.RESUME,
                RvcTrainingRecoveryAction.RETRY_SAFE_BATCH,
            }
            and self._state is not None
            and self._state.can_resume
        ):
            self.resume_mode_button.setChecked(True)
        self._request_start()

    def _sync_interval_limit(self, target_epoch: int) -> None:
        self.save_interval_spin.setMaximum(max(1, target_epoch))
        self._target_epoch = max(1, int(target_epoch))
        self._sync_epoch_label()

    def _sync_action_text(self) -> None:
        can_resume = self._state is not None and self._state.can_resume
        action = (
            "Resume Training"
            if can_resume and self.resume_mode_button.isChecked()
            else "Start Training"
        )
        set_translated_text(self.start_button, action)
        self._sync_start_hint()

    def _sync_training_mode(self, _checked: bool = False) -> None:
        can_resume = self._state is not None and self._state.can_resume
        resume = can_resume and self.resume_mode_button.isChecked()
        minimum = self._state.current_epoch + 1 if resume and self._state is not None else 1
        self.target_epoch_spin.setMinimum(minimum)
        if self._active_preset != RvcTrainingPresetId.CUSTOM:
            self._apply_preset(self._active_preset)
        elif resume and self.target_epoch_spin.value() < minimum:
            self.target_epoch_spin.setValue(minimum)
        self._sync_epoch_label()
        self._sync_action_text()

    def _sync_enabled_state(self) -> None:
        can_train = self._record is not None and self._record.is_managed
        settings_enabled = can_train and not self._is_running
        for control in (
            self.target_epoch_spin,
            self.batch_size_spin,
            self.save_interval_spin,
        ):
            control.setEnabled(settings_enabled)
        self.gpu_index_spin.setEnabled(settings_enabled and self._training_accelerated)
        self.mode_control.setEnabled(settings_enabled)
        self.preset_control.setEnabled(settings_enabled)
        self.start_button.setEnabled(
            can_train and self._preflight.can_start and not self._is_running
        )
        recovery_action = (
            self._recovery_advice.action if self._recovery_advice is not None else None
        )
        recovery_needs_ready_state = recovery_action in {
            RvcTrainingRecoveryAction.RETRY,
            RvcTrainingRecoveryAction.RESUME,
            RvcTrainingRecoveryAction.RETRY_SAFE_BATCH,
        }
        self.recovery_primary_button.setEnabled(
            not self._is_running
            and (
                not recovery_needs_ready_state
                or (can_train and self._preflight.can_start)
            )
        )
        self.recovery_diagnostics_button.setEnabled(
            not self._is_running and bool(self._recovery_task_id)
        )
        self.stop_button.setEnabled(self._is_running)
        self._sync_start_hint()
        self._sync_recovery_visibility()

    def _sync_epoch_label(self) -> None:
        can_resume = self._state is not None and self._state.can_resume
        starting_epoch = (
            self._state.current_epoch
            if can_resume and self.resume_mode_button.isChecked() and self._state is not None
            else 0
        )
        self._current_epoch = starting_epoch
        self.epoch_label.setText(f"{starting_epoch} / {self.target_epoch_spin.value()}")

    def _sync_preflight(self) -> None:
        if self._preflight.blockers:
            status = "blocked"
            text = "Action Required"
        elif self._preflight.warnings:
            status = "review"
            text = "Ready with Warnings"
        else:
            status = "ready"
            text = "Ready"
        set_translated_text(self.readiness_badge, text)
        self.readiness_badge.setProperty("readiness", status)
        self.readiness_badge.style().unpolish(self.readiness_badge)
        self.readiness_badge.style().polish(self.readiness_badge)
        for check in self._preflight.checks:
            row = self.preflight_rows.get(check.key)
            if row is None:
                continue
            frame, title, detail = row
            set_translated_text(title, check.label)
            set_translated_text(detail, check.detail, **check.format_values)
            frame.setProperty("checkLevel", check.level.value)
            frame.style().unpolish(frame)
            frame.style().polish(frame)

    def _sync_start_hint(self) -> None:
        show_hint = True
        if self._record is None:
            text = "Select a model"
            values: dict[str, object] = {}
        elif not self._record.is_managed:
            text = "Import a managed copy to train"
            values = {}
        elif self._total_items == 0:
            text = "Add training materials before starting"
            values = {}
        elif self._ready_items < self._total_items:
            text = "Review every training material before starting"
            values = {}
        elif self._preflight.blockers:
            blocker = self._preflight.blockers[0]
            text = blocker.detail
            values = blocker.format_values
        elif (
            self._state is not None
            and self._state.can_resume
            and self.resume_mode_button.isChecked()
        ):
            text = "Continue from epoch {epoch}"
            values = {"epoch": self._state.current_epoch}
        else:
            text = "Ready to train"
            values = {}
            show_hint = False
        set_translated_text(self.start_hint_label, text, **values)
        self.start_hint_label.setVisible(not self._is_running and show_hint)

    def _select_preset(self, preset_id: RvcTrainingPresetId) -> None:
        if preset_id == RvcTrainingPresetId.CUSTOM:
            self._active_preset = preset_id
            self._sync_preset_summary()
            self._sync_info_popovers()
            return
        self._apply_preset(preset_id)

    def _apply_preset(self, preset_id: RvcTrainingPresetId) -> None:
        recommendation = recommend_rvc_training_settings(
            preset_id,
            current_epoch=self._preset_epoch_base(),
            accelerated=self._training_accelerated,
            adapter_memory_bytes=self._adapter_memory_bytes,
        )
        self._applying_preset = True
        try:
            self.target_epoch_spin.setValue(recommendation.target_epoch)
            self.batch_size_spin.setValue(recommendation.batch_size)
            self.save_interval_spin.setValue(recommendation.checkpoint_interval)
            self._active_preset = preset_id
            self.preset_buttons[preset_id].setChecked(True)
        finally:
            self._applying_preset = False
        self._sync_preset_summary()
        self._sync_info_popovers()

    def _mark_custom_settings(self, _value: int) -> None:
        if self._applying_preset:
            return
        self._active_preset = RvcTrainingPresetId.CUSTOM
        self.preset_buttons[RvcTrainingPresetId.CUSTOM].setChecked(True)
        self._sync_preset_summary()
        self._sync_info_popovers()

    def _sync_preset_from_settings(self) -> None:
        for preset_id in TRAINING_PRESETS:
            recommendation = recommend_rvc_training_settings(
                preset_id,
                current_epoch=self._preset_epoch_base(),
                accelerated=self._training_accelerated,
                adapter_memory_bytes=self._adapter_memory_bytes,
            )
            if (
                self.target_epoch_spin.value() == recommendation.target_epoch
                and self.batch_size_spin.value() == recommendation.batch_size
                and self.save_interval_spin.value() == recommendation.checkpoint_interval
            ):
                self._active_preset = preset_id
                self.preset_buttons[preset_id].setChecked(True)
                self._sync_preset_summary()
                self._sync_info_popovers()
                return
        self._active_preset = RvcTrainingPresetId.CUSTOM
        self.preset_buttons[RvcTrainingPresetId.CUSTOM].setChecked(True)
        self._sync_preset_summary()
        self._sync_info_popovers()

    def _preset_epoch_base(self) -> int:
        if (
            self._state is not None
            and self._state.can_resume
            and self.resume_mode_button.isChecked()
        ):
            return self._state.current_epoch
        return 0

    def _sync_preset_summary(self) -> None:
        if self._active_preset == RvcTrainingPresetId.CUSTOM:
            purpose = tr("Manual training settings")
        else:
            purpose = tr(TRAINING_PRESETS[self._active_preset].purpose)
        environment = self._training_environment_summary()
        self.preset_summary_label.setText(
            tr(
                "{purpose} | target {epochs} | batch {batch} | save every {interval} | {environment}",
                purpose=purpose,
                epochs=self.target_epoch_spin.value(),
                batch=self.batch_size_spin.value(),
                interval=self.save_interval_spin.value(),
                environment=environment,
            )
        )

    def _sync_info_popovers(self) -> None:
        self.target_epoch_info.set_content(
            tr("Target Epoch"),
            tr(
                "The number of times the trainer processes the complete dataset. "
                "Too many epochs can overfit the source material."
            ),
            tr(
                "Current recommendation: {value}",
                value=self.target_epoch_spin.value(),
            ),
        )
        self.batch_size_info.set_content(
            tr("Batch Size"),
            tr(
                "The number of training samples processed together. Larger batches use "
                "more memory; smaller batches are safer on limited hardware."
            ),
            tr(
                "Current recommendation: {value} ({environment})",
                value=self.batch_size_spin.value(),
                environment=self._training_environment_summary(),
            ),
        )
        self.checkpoint_interval_info.set_content(
            tr("Checkpoint Interval"),
            tr(
                "How often recoverable G/D checkpoints are saved. Shorter intervals "
                "improve recovery but write files more often."
            ),
            tr(
                "Current recommendation: every {value} epochs",
                value=self.save_interval_spin.value(),
            ),
        )
        if self._training_accelerated:
            device_body = tr(
                "GPU index 0 selects the first detected training GPU. CPU mode ignores "
                "this value and trains more slowly."
            )
            device_recommendation = tr(
                "Use GPU 0 unless this PC has multiple training GPUs."
            )
        else:
            device_body = tr(
                "This hardware profile uses the CPU for model training. No GPU index is required."
            )
            device_recommendation = (
                tr("Voice conversion still uses the AMD GPU through DirectML.")
                if self._inference_backend == RvcComputeBackend.DIRECTML
                else tr("CPU training takes longer but remains fully supported.")
            )
        self.training_device_info.set_content(
            tr("Training Device"),
            device_body,
            device_recommendation,
        )

    def _training_environment_summary(self) -> str:
        if not self._training_accelerated:
            return tr("Conservative CPU recommendation")
        device = self._adapter_name or tr("Detected GPU")
        if self._adapter_memory_bytes <= 0:
            return tr("Recommended for {device}", device=device)
        return tr(
            "Recommended for {device} ({memory} GB VRAM)",
            device=device,
            memory=f"{self._adapter_memory_bytes / 1024**3:.1f}",
        )

    def _sync_workflow_for_phase(self, phase: RvcTrainingPhase) -> None:
        if phase in {RvcTrainingPhase.COMPLETE, RvcTrainingPhase.INDEX_READY}:
            self._active_stage_key = ""
            self.workflow_progress.set_status(
                completed_keys=("data", "prepare", "features", "train", "index")
            )
            self.set_progress(100)
            return
        active_key = {
            RvcTrainingPhase.PREPROCESS: "prepare",
            RvcTrainingPhase.PREPROCESSED: "features",
            RvcTrainingPhase.EXTRACT: "features",
            RvcTrainingPhase.FEATURES_READY: "features",
            RvcTrainingPhase.FILELIST_READY: "features",
            RvcTrainingPhase.TRAIN: "train",
            RvcTrainingPhase.STOPPED: "train" if self._current_epoch else "",
            RvcTrainingPhase.INDEX: "index",
            RvcTrainingPhase.FAILED: "train" if self._current_epoch else "data",
        }.get(phase, "")
        self._active_stage_key = active_key
        self.workflow_progress.set_status(
            active_key,
            completed_keys=_completed_workflow_stages(active_key),
            failed=phase == RvcTrainingPhase.FAILED,
        )
        if not self._is_running:
            if phase in {
                RvcTrainingPhase.TRAIN,
                RvcTrainingPhase.STOPPED,
                RvcTrainingPhase.FAILED,
            } and self._state is not None:
                epoch_fraction = self._state.current_epoch / max(
                    1,
                    self._state.target_epoch,
                )
                self.set_progress(32 + round(63 * min(1.0, epoch_fraction)))
            else:
                self.set_progress(
                    {
                        RvcTrainingPhase.IDLE: 0,
                        RvcTrainingPhase.PREPROCESS: 5,
                        RvcTrainingPhase.PREPROCESSED: 15,
                        RvcTrainingPhase.EXTRACT: 15,
                        RvcTrainingPhase.FEATURES_READY: 25,
                        RvcTrainingPhase.FILELIST_READY: 28,
                        RvcTrainingPhase.INDEX: 95,
                    }.get(phase, 0)
                )

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


def _field_label_with_info(
    text: str,
    info_button: InfoPopoverButton,
) -> tuple[QWidget, QLabel]:
    header = QWidget()
    header.setObjectName("TrainingFieldHeader")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = _field_label(text)
    layout.addWidget(label)
    layout.addWidget(info_button)
    layout.addStretch(1)
    return header, label


def _training_metric(caption: str) -> tuple[QFrame, QLabel]:
    metric = QFrame()
    metric.setObjectName("TrainingMetric")
    layout = QVBoxLayout(metric)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(3)
    caption_label = QLabel(caption)
    caption_label.setObjectName("TrainingMetricLabel")
    value_label = QLabel("--")
    value_label.setObjectName("TrainingMetricValue")
    layout.addWidget(caption_label)
    layout.addWidget(value_label)
    return metric, value_label


def _training_preflight_check() -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("TrainingPreflightCheck")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(11, 9, 11, 9)
    layout.setSpacing(3)

    title = QLabel()
    title.setObjectName("TrainingPreflightTitle")
    detail = QLabel()
    detail.setObjectName("TrainingPreflightDetail")
    layout.addWidget(title)
    layout.addWidget(detail)
    configure_two_line_status_text(frame, title, detail, spacing=layout.spacing())
    return frame, title, detail


def _workflow_key_for_stage(stage: str) -> str:
    return {
        "Preparing Training": "data",
        "Preparing Audio": "prepare",
        "Extracting Features": "features",
        "Building File List": "features",
        "Preparing Spectrograms": "features",
        "Training": "train",
        "Training Model": "train",
        "Building Index": "index",
        "Registering Model": "index",
    }.get(stage, "")


def _completed_workflow_stages(active_key: str) -> tuple[str, ...]:
    order = ("data", "prepare", "features", "train", "index")
    try:
        active_index = order.index(active_key)
    except ValueError:
        return ()
    return order[:active_index]


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


def format_training_elapsed(total_seconds: int) -> str:
    hours, remainder = divmod(max(0, int(total_seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
