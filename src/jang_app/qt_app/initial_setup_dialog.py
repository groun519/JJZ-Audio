from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import theme_tokens
from jang_app.services.app_paths import AppPaths
from jang_app.services.app_update import DEFAULT_MANIFEST_URL
from jang_app.services.i18n import tr
from jang_app.services.initial_setup import (
    InitialSetupError,
    complete_initial_setup,
    persist_storage_layout,
    prepare_storage_layout,
)
from jang_app.services.hardware_diagnostics_state import record_hardware_diagnostics
from jang_app.services.rvc_inference_runtime import clear_rvc_inference_probe_cache
from jang_app.services.rvc_runtime_profile import clear_nvidia_gpu_cache
from jang_app.services.system_diagnostics import (
    DiagnosticCheck,
    DiagnosticStatus,
    SystemDiagnostics,
    run_system_diagnostics,
)
from jang_app.services.runtime_bootstrap import (
    RuntimeProvisionActivity,
    RuntimeProvisionStage,
    provision_ai_runtime,
    provision_ai_runtime_offline,
)


_DIAGNOSTIC_KEYS = (
    "storage",
    "ffmpeg",
    "demucs",
    "rvc_assets",
    "ai_runtime",
    "cuda",
)
_DIAGNOSTIC_STAGE_LABELS = (
    "Storage",
    "Media Tools",
    "Separation",
    "Voice Tools",
    "Audio Engine",
    "GPU",
)
_INSTALL_STAGE_LABELS = (
    "Prepare",
    "Download",
    "Install",
    "Configure",
    "Verify",
)


class DiagnosticsWorker(QThread):
    check_ready = Signal(object)
    stage_started = Signal(str, int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paths: AppPaths,
        *,
        refresh_runtime: bool = False,
        refresh_hardware: bool = False,
    ) -> None:
        super().__init__()
        self._paths = paths
        self._refresh_runtime = refresh_runtime
        self._refresh_hardware = refresh_hardware

    def run(self) -> None:
        try:
            if self._refresh_runtime:
                clear_rvc_inference_probe_cache()
            if self._refresh_hardware:
                clear_nvidia_gpu_cache()
            result = run_system_diagnostics(
                self._paths,
                reporter=self.check_ready.emit,
                stage_reporter=self.stage_started.emit,
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class RuntimeProvisionWorker(QThread):
    progress_changed = Signal(int)
    activity_changed = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paths: AppPaths,
        manifest_url: str,
        package_index: Path | None = None,
    ) -> None:
        super().__init__()
        self._paths = paths
        self._manifest_url = manifest_url
        self._package_index = package_index

    def run(self) -> None:
        try:
            if self._package_index is None:
                result = provision_ai_runtime(
                    self._paths,
                    manifest_url=self._manifest_url,
                    progress=self.progress_changed.emit,
                    activity=self.activity_changed.emit,
                )
            else:
                result = provision_ai_runtime_offline(
                    self._paths,
                    self._package_index,
                    progress=self.progress_changed.emit,
                    activity=self.activity_changed.emit,
                )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class InitialSetupDialog(AppDialog):
    def __init__(
        self,
        paths: AppPaths,
        logo_path: Path,
        *,
        first_run: bool = True,
        diagnostics_only: bool = False,
        theme_mode: str = "dark",
        diagnostics_worker_type: type[DiagnosticsWorker] = DiagnosticsWorker,
        runtime_worker_type: type[RuntimeProvisionWorker] = RuntimeProvisionWorker,
    ) -> None:
        dialog_title = tr("First Run Setup" if first_run else "System Setup")
        super().__init__(
            dialog_title,
            logo_path,
            theme_mode=theme_mode,
            allow_minimize=True,
            allow_maximize=True,
        )
        self._paths = paths
        self._configured_paths = paths
        self._first_run = first_run
        self._diagnostics_only = diagnostics_only
        self._theme_mode = theme_mode
        self._diagnostics_worker_type = diagnostics_worker_type
        self._runtime_worker_type = runtime_worker_type
        self._worker: QThread | None = None
        self._diagnostics: SystemDiagnostics | None = None
        self.restart_required = False

        self.setMinimumSize(780, 560)
        self.resize(820, 590)
        self.setStyleSheet(_build_setup_stylesheet(theme_mode))
        self._build_ui()
        if diagnostics_only:
            self.stack.setCurrentIndex(1)
            self.step_label.setText(tr("SYSTEM CHECK"))
            self.step_count_label.setText("01 / 01")
            self.back_button.hide()
            self.primary_button.setText(tr("Close"))
            QTimer.singleShot(0, self._start_diagnostics)

    @property
    def configured_paths(self) -> AppPaths:
        return self._configured_paths

    @property
    def diagnostics(self) -> SystemDiagnostics | None:
        return self._diagnostics

    def _build_ui(self) -> None:
        header = QFrame()
        header.setObjectName("SetupHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(13)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        title = QLabel(tr("First Run Setup" if self._first_run else "System Setup"))
        title.setObjectName("SetupBrand")
        self.step_label = QLabel(tr("STORAGE SETUP"))
        self.step_label.setObjectName("SetupStep")
        identity.addWidget(title)
        identity.addWidget(self.step_label)
        header_layout.addLayout(identity)
        header_layout.addStretch(1)
        self.step_count_label = QLabel("01 / 02")
        self.step_count_label.setObjectName("SetupStepCount")
        header_layout.addWidget(self.step_count_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_storage_page())
        self.stack.addWidget(self._build_diagnostics_page())

        self.status_label = QLabel("")
        self.status_label.setObjectName("SetupError")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setObjectName("SetupSecondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton(tr("Back"))
        self.back_button.setObjectName("SetupSecondaryButton")
        self.back_button.clicked.connect(self._go_back)
        self.back_button.hide()
        self.primary_button = QPushButton(tr("Continue"))
        self.primary_button.setObjectName("SetupPrimaryButton")
        self.primary_button.clicked.connect(self._advance)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        footer.addWidget(self.back_button)
        footer.addWidget(self.primary_button)

        layout = self.content_layout
        layout.addWidget(header)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 22, 24, 20)
        body_layout.setSpacing(14)
        body_layout.addWidget(self.stack, 1)
        body_layout.addWidget(self.status_label)
        body_layout.addLayout(footer)
        layout.addWidget(body, 1)

    def _build_storage_page(self) -> QWidget:
        page = QWidget()
        title = QLabel(tr("Choose Media Storage"))
        title.setObjectName("SetupTitle")
        description = QLabel(tr("Songs, models, and rendered files are kept together in this location."))
        description.setObjectName("SetupDescription")

        media_card = QFrame()
        media_card.setObjectName("SetupCard")
        media_layout = QVBoxLayout(media_card)
        media_layout.setContentsMargins(18, 16, 18, 16)
        media_layout.setSpacing(9)
        media_label = QLabel(tr("Media Storage"))
        media_label.setObjectName("SetupFieldLabel")
        self.media_edit = QLineEdit(str(self._paths.workspace_anchor))
        self.media_edit.setObjectName("SetupPathEdit")
        self.media_edit.textChanged.connect(self._update_storage_preview)
        browse = QPushButton(tr("Browse"))
        browse.setObjectName("SetupBrowseButton")
        browse.clicked.connect(self._browse_media_root)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self.media_edit, 1)
        input_row.addWidget(browse)
        media_layout.addWidget(media_label)
        media_layout.addLayout(input_row)

        preview = QFrame()
        preview.setObjectName("SetupPreview")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(7)
        self.workspace_preview = _path_preview("Workspace")
        self.output_preview = _path_preview("Output")
        self.data_preview = _path_preview("App Data")
        preview_layout.addWidget(self.workspace_preview)
        preview_layout.addWidget(self.output_preview)
        preview_layout.addWidget(self.data_preview)
        self._update_storage_preview()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(media_card)
        layout.addWidget(preview)
        layout.addStretch(1)
        return page

    def _build_diagnostics_page(self) -> QWidget:
        page = QWidget()
        title = QLabel(tr("System Diagnostics"))
        title.setObjectName("SetupTitle")
        self.diagnostic_summary = QLabel(tr("Checking bundled tools and GPU acceleration..."))
        self.diagnostic_summary.setObjectName("SetupDescription")
        self.diagnostic_progress_detail = QLabel("")
        self.diagnostic_progress_detail.setObjectName("SetupProgressDetail")
        self.diagnostic_progress_detail.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        progress_header.addWidget(self.diagnostic_summary, 1)
        progress_header.addWidget(self.diagnostic_progress_detail)
        self.diagnostic_progress = QProgressBar()
        self.diagnostic_progress.setRange(0, 0)
        self.diagnostic_progress.setTextVisible(False)
        self.diagnostic_progress.setObjectName("SetupProgress")
        self.diagnostic_progress.hide()
        self.diagnostic_stages = SetupStageStrip()
        self.diagnostic_stages.hide()

        checks = (
            ("storage", "Storage"),
            ("ffmpeg", "FFmpeg"),
            ("demucs", "Vocal Separation Model"),
            ("rvc_assets", "Voice Conversion Tools"),
            ("ai_runtime", "Audio Engine"),
            ("cuda", "GPU Acceleration"),
        )
        self.diagnostic_rows: dict[str, DiagnosticRow] = {}
        checks_layout = QVBoxLayout()
        checks_layout.setContentsMargins(0, 0, 0, 0)
        checks_layout.setSpacing(7)
        for key, label in checks:
            row = DiagnosticRow(tr(label))
            self.diagnostic_rows[key] = row
            checks_layout.addWidget(row)

        self.rerun_button = QPushButton(tr("Run Diagnostics Again"))
        self.rerun_button.setObjectName("SetupSecondaryButton")
        self.rerun_button.clicked.connect(
            lambda _checked=False: self._start_diagnostics(
                refresh_runtime=True,
                refresh_hardware=True,
            )
        )
        self.rerun_button.hide()
        self.install_runtime_button = QPushButton(tr("Install Audio Engine"))
        self.install_runtime_button.setObjectName("SetupPrimaryButton")
        self.install_runtime_button.clicked.connect(lambda: self._start_runtime_install())
        self.install_runtime_button.hide()
        self.offline_runtime_button = QPushButton(tr("Install from Files"))
        self.offline_runtime_button.setObjectName("SetupSecondaryButton")
        self.offline_runtime_button.clicked.connect(self._choose_runtime_packages)
        self.offline_runtime_button.hide()
        rerun_row = QHBoxLayout()
        rerun_row.addWidget(self.install_runtime_button)
        rerun_row.addWidget(self.offline_runtime_button)
        rerun_row.addStretch(1)
        rerun_row.addWidget(self.rerun_button)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(title)
        layout.addLayout(progress_header)
        layout.addWidget(self.diagnostic_progress)
        layout.addWidget(self.diagnostic_stages)
        layout.addLayout(checks_layout)
        layout.addLayout(rerun_row)
        layout.addStretch(1)
        return page

    def _browse_media_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("Choose Media Storage"), self.media_edit.text())
        if selected:
            self.media_edit.setText(selected)

    def _update_storage_preview(self) -> None:
        media = Path(self.media_edit.text().strip()).expanduser()
        self.workspace_preview.setText(f"{tr('Workspace')}  ·  {media / 'workspace'}")
        self.output_preview.setText(f"{tr('Output')}  ·  {media / 'output'}")
        self.data_preview.setText(f"{tr('App Data')}  ·  {self._paths.data_root}")

    def _advance(self) -> None:
        if self.stack.currentIndex() == 0:
            self._prepare_storage()
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if self._diagnostics is None:
            self._start_diagnostics()
            return
        if self._first_run:
            complete_initial_setup(self._configured_paths, diagnostics_ready=self._diagnostics.ready)
        else:
            persist_storage_layout(self._configured_paths)
        record_hardware_diagnostics(self._configured_paths, self._diagnostics)
        self.restart_required = self._configured_paths.workspace_anchor != self._paths.workspace_anchor
        self.accept()

    def _prepare_storage(self) -> None:
        try:
            self._configured_paths = prepare_storage_layout(
                self._paths,
                Path(self.media_edit.text().strip()),
            )
        except (InitialSetupError, OSError) as exc:
            self._show_error(str(exc))
            return
        self._show_error("")
        self.stack.setCurrentIndex(1)
        self.step_label.setText(tr("SYSTEM CHECK"))
        self.step_count_label.setText("02 / 02")
        self.back_button.show()
        self._start_diagnostics()

    def _go_back(self) -> None:
        if self._diagnostics_only:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.stack.setCurrentIndex(0)
        self.step_label.setText(tr("STORAGE SETUP"))
        self.step_count_label.setText("01 / 02")
        self.back_button.hide()
        self.primary_button.setText(tr("Continue"))
        self.cancel_button.show()

    def _start_diagnostics(
        self,
        *,
        refresh_runtime: bool = False,
        refresh_hardware: bool = False,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._diagnostics = None
        for row in self.diagnostic_rows.values():
            row.set_pending()
        self.diagnostic_summary.setText(tr("Checking bundled tools and GPU acceleration..."))
        self.diagnostic_progress_detail.setText(f"0 / {len(_DIAGNOSTIC_KEYS)}")
        self.diagnostic_progress_detail.show()
        self.diagnostic_progress.show()
        self.diagnostic_progress.setRange(0, len(_DIAGNOSTIC_KEYS))
        self.diagnostic_progress.setValue(0)
        self.diagnostic_stages.set_stages(tuple(tr(label) for label in _DIAGNOSTIC_STAGE_LABELS))
        self.diagnostic_stages.show()
        self.rerun_button.hide()
        self.install_runtime_button.hide()
        self.offline_runtime_button.hide()
        self.primary_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        worker = self._diagnostics_worker_type(
            self._configured_paths,
            refresh_runtime=refresh_runtime,
            refresh_hardware=refresh_hardware,
        )
        worker.setParent(self)
        worker.check_ready.connect(self._on_check_ready)
        worker.stage_started.connect(self._on_diagnostic_stage_started)
        worker.completed.connect(self._on_diagnostics_complete)
        worker.failed.connect(self._on_diagnostics_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_diagnostic_stage_started(self, key: str, position: int, total: int) -> None:
        row = self.diagnostic_rows.get(key)
        if row is not None:
            row.set_running(tr("Checking"))
        self.diagnostic_stages.set_active(position - 1)
        self.diagnostic_progress.setValue(max(0, position - 1))
        self.diagnostic_progress_detail.setText(f"{position} / {total}")

    def _on_check_ready(self, check: object) -> None:
        if isinstance(check, DiagnosticCheck) and check.key in self.diagnostic_rows:
            self.diagnostic_rows[check.key].set_check(check)
            position = _DIAGNOSTIC_KEYS.index(check.key) + 1
            self.diagnostic_progress.setValue(position)
            self.diagnostic_progress_detail.setText(
                f"{position} / {len(_DIAGNOSTIC_KEYS)}"
            )
            self.diagnostic_stages.set_completed(position - 1)

    def _on_diagnostics_complete(self, diagnostics: object) -> None:
        if not isinstance(diagnostics, SystemDiagnostics):
            self._on_diagnostics_failed("Diagnostics returned an invalid result.")
            return
        self._diagnostics = diagnostics
        if self._diagnostics_only:
            record_hardware_diagnostics(self._configured_paths, diagnostics)
        for check in diagnostics.checks:
            self._on_check_ready(check)
        if diagnostics.ready and diagnostics.has_warnings:
            summary = "Setup is usable, but GPU acceleration needs attention."
        elif diagnostics.ready:
            summary = "This PC is ready for JJZero Audio."
        elif any(
            check.status == DiagnosticStatus.REQUIRED for check in diagnostics.checks
        ):
            summary = "Required audio processing components are not installed yet."
        else:
            summary = "Some bundled components are unavailable. Rebuild or repair the installation."
        self.diagnostic_summary.setText(tr(summary))
        self.diagnostic_progress.hide()
        self.diagnostic_progress_detail.hide()
        self.diagnostic_stages.hide()
        self.rerun_button.show()
        needs_runtime = _needs_runtime_install(diagnostics)
        self.install_runtime_button.setVisible(needs_runtime)
        self.offline_runtime_button.setVisible(needs_runtime)
        self.primary_button.setText(tr("Start JJZero Audio" if self._first_run else "Apply and Restart"))
        self.primary_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        if not self._first_run and self._configured_paths.workspace_anchor == self._paths.workspace_anchor:
            self.primary_button.setText(tr("Close"))

    def _on_diagnostics_failed(self, error: str) -> None:
        self._diagnostics = SystemDiagnostics(
            (DiagnosticCheck("ai_runtime", "Audio Engine", DiagnosticStatus.FAIL, error),)
        )
        self._on_check_ready(self._diagnostics.checks[0])
        self.diagnostic_summary.setText(tr("System diagnostics failed."))
        self.diagnostic_progress.hide()
        self.diagnostic_progress_detail.hide()
        self.diagnostic_stages.hide()
        self.rerun_button.show()
        self.install_runtime_button.show()
        self.offline_runtime_button.show()
        if self._first_run:
            action = "Start JJZero Audio"
        elif self._configured_paths.workspace_anchor != self._paths.workspace_anchor:
            action = "Apply and Restart"
        else:
            action = "Close"
        self.primary_button.setText(tr(action))
        self.primary_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def _choose_runtime_packages(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select Audio Engine Package Index"),
            str(Path.home()),
            f"{tr('JSON Files')} (*.json)",
        )
        if selected:
            self._start_runtime_install(Path(selected))

    def _start_runtime_install(self, package_index: Path | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.setProperty("runtimeInstallFailed", False)
        self.diagnostic_summary.setText(tr("Preparing audio processing components..."))
        self.diagnostic_progress_detail.setText("0%")
        self.diagnostic_progress_detail.show()
        self.diagnostic_progress.setRange(0, 100)
        self.diagnostic_progress.setValue(0)
        self.diagnostic_progress.show()
        self.diagnostic_stages.set_stages(tuple(tr(label) for label in _INSTALL_STAGE_LABELS))
        self.diagnostic_stages.set_active(0)
        self.diagnostic_stages.show()
        for key in ("ffmpeg", "demucs", "rvc_assets", "ai_runtime"):
            self.diagnostic_rows[key].set_pending(
                tr("Queued for installation"),
                status=tr("Waiting"),
            )
        self.diagnostic_rows["cuda"].set_pending(
            tr("Checked after installation"),
            status=tr("Waiting"),
        )
        self.install_runtime_button.hide()
        self.offline_runtime_button.hide()
        self.rerun_button.hide()
        self.primary_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        manifest_url = os.environ.get("JJZERO_UPDATE_MANIFEST_URL", DEFAULT_MANIFEST_URL)
        worker = self._runtime_worker_type(
            self._configured_paths,
            manifest_url,
            package_index,
        )
        worker.setParent(self)
        worker.progress_changed.connect(self._on_runtime_progress)
        worker.activity_changed.connect(self._on_runtime_activity)
        worker.completed.connect(self._on_runtime_installed)
        worker.failed.connect(self._on_runtime_install_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(self._restart_diagnostics_after_runtime_install)
        self._worker = worker
        worker.start()

    def _on_runtime_progress(self, value: int) -> None:
        self.diagnostic_progress.setValue(value)
        if "/" not in self.diagnostic_progress_detail.text():
            self.diagnostic_progress_detail.setText(f"{value}%")

    def _on_runtime_activity(self, activity: object) -> None:
        if not isinstance(activity, RuntimeProvisionActivity):
            return
        stages = tuple(RuntimeProvisionStage)
        position = stages.index(activity.stage)
        self.diagnostic_stages.set_active(position)
        summaries = {
            RuntimeProvisionStage.PREPARING: "Preparing audio processing components...",
            RuntimeProvisionStage.DOWNLOADING: "Downloading audio processing components...",
            RuntimeProvisionStage.INSTALLING: "Installing audio tools and model components...",
            RuntimeProvisionStage.CONFIGURING: "Configuring hardware acceleration...",
            RuntimeProvisionStage.VERIFYING: "Verifying audio processing components...",
        }
        self.diagnostic_summary.setText(tr(summaries[activity.stage]))
        if activity.total_bytes > 0:
            percent = min(100, int(activity.completed_bytes * 100 / activity.total_bytes))
            self.diagnostic_progress.setRange(0, 100)
            self.diagnostic_progress.setValue(percent)
            self.diagnostic_progress_detail.setText(
                f"{_format_bytes(activity.completed_bytes)} / "
                f"{_format_bytes(activity.total_bytes)} · {percent}%"
            )
        else:
            self.diagnostic_progress_detail.setText(tr(activity.detail))
            if activity.stage == RuntimeProvisionStage.VERIFYING:
                self.diagnostic_progress.setRange(0, 0)
        if activity.stage == RuntimeProvisionStage.DOWNLOADING:
            for key in ("ffmpeg", "demucs", "rvc_assets", "ai_runtime"):
                self.diagnostic_rows[key].set_running(tr("Downloading"))
        elif activity.stage == RuntimeProvisionStage.INSTALLING:
            for key in ("ffmpeg", "demucs", "rvc_assets", "ai_runtime"):
                self.diagnostic_rows[key].set_running(tr("Installing"))
        elif activity.stage == RuntimeProvisionStage.CONFIGURING:
            self.diagnostic_rows["rvc_assets"].set_running(tr("Configuring"))
            self.diagnostic_rows["ai_runtime"].set_running(tr("Configuring"))
        elif activity.stage == RuntimeProvisionStage.VERIFYING:
            self.diagnostic_rows["ai_runtime"].set_running(tr("Verifying"))
            self.diagnostic_rows["cuda"].set_running(tr("Verifying"))

    def _on_runtime_installed(self, _result: object) -> None:
        self.diagnostic_summary.setText(tr("Audio engine installed. Verifying..."))
        self.diagnostic_stages.set_active(len(_INSTALL_STAGE_LABELS) - 1)

    def _on_runtime_install_failed(self, error: str) -> None:
        self.diagnostic_summary.setText(f"{tr('Audio engine installation failed')}: {error}")
        self.diagnostic_progress.hide()
        self.diagnostic_progress_detail.hide()
        self.diagnostic_stages.hide()
        self.install_runtime_button.show()
        self.offline_runtime_button.show()
        self.rerun_button.show()
        self.primary_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.setProperty("runtimeInstallFailed", True)

    def _restart_diagnostics_after_runtime_install(self) -> None:
        failed = bool(self.property("runtimeInstallFailed"))
        self.setProperty("runtimeInstallFailed", False)
        if not failed:
            self._start_diagnostics(refresh_runtime=True)

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)


class DiagnosticRow(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("DiagnosticRow")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DiagnosticTitle")
        self.detail_label = QLabel(tr("Not checked"))
        self.detail_label.setObjectName("DiagnosticDetail")
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label = QLabel("—")
        self.status_label.setObjectName("DiagnosticStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title_label)
        text.addWidget(self.detail_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 12, 9)
        layout.addLayout(text, 1)
        layout.addWidget(self.status_label)

    def set_pending(self, detail: str = "", *, status: str = "") -> None:
        text = detail or tr("Not checked")
        self.detail_label.setText(text)
        self.detail_label.setToolTip(text)
        self.status_label.setText(status or tr("Not Checked"))
        self._set_status("pending")

    def set_running(self, detail: str = "") -> None:
        text = detail or tr("Checking")
        self.detail_label.setText(text)
        self.detail_label.setToolTip(text)
        self.status_label.setText(tr("In Progress"))
        self._set_status("running")

    def set_check(self, check: DiagnosticCheck) -> None:
        self.detail_label.setText(tr(check.detail))
        self.detail_label.setToolTip(check.detail)
        label = {
            DiagnosticStatus.PASS: "Ready",
            DiagnosticStatus.WARNING: "Attention",
            DiagnosticStatus.REQUIRED: "Install Required",
            DiagnosticStatus.SKIPPED: "Not Checked",
            DiagnosticStatus.FAIL: "Failed",
        }[check.status]
        self.status_label.setText(tr(label))
        self._set_status(check.status.value)

    def _set_status(self, status: str) -> None:
        self.setProperty("status", status)
        self.status_label.setProperty("status", status)
        for widget in (self, self.status_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class SetupStageStrip(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SetupStageStrip")
        self._labels: list[QLabel] = []
        self._active = -1
        self._completed = -1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(5, 4, 5, 4)
        self._layout.setSpacing(4)

    def set_stages(self, stages: tuple[str, ...]) -> None:
        while self._labels:
            label = self._labels.pop()
            self._layout.removeWidget(label)
            label.deleteLater()
        self._active = -1
        self._completed = -1
        for position, text in enumerate(stages, start=1):
            label = QLabel(f"{position:02d}  {text}")
            label.setObjectName("SetupStageBadge")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(label, 1)
            self._labels.append(label)
        self._refresh()

    def set_active(self, position: int) -> None:
        if not self._labels:
            return
        self._active = min(max(0, position), len(self._labels) - 1)
        self._completed = max(self._completed, self._active - 1)
        self._refresh()

    def set_completed(self, position: int) -> None:
        self._completed = min(max(self._completed, position), len(self._labels) - 1)
        self._refresh()

    def _refresh(self) -> None:
        for index, label in enumerate(self._labels):
            state = (
                "complete"
                if index <= self._completed
                else "active"
                if index == self._active
                else "pending"
            )
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)


def _needs_runtime_install(diagnostics: SystemDiagnostics) -> bool:
    runtime_keys = {"ffmpeg", "demucs", "rvc_assets", "ai_runtime"}
    return any(
        check.key in runtime_keys
        and check.status in {DiagnosticStatus.FAIL, DiagnosticStatus.REQUIRED}
        for check in diagnostics.checks
    )


def _format_bytes(value: int) -> str:
    size = max(0, value)
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def _path_preview(label: str) -> QLabel:
    preview = QLabel(label)
    preview.setObjectName("SetupPathPreview")
    preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return preview


def _build_setup_stylesheet(theme_mode: str) -> str:
    colors = theme_tokens(theme_mode)
    input_color = "#191918" if theme_mode == "dark" else colors["background"]
    warning_text = "#f0dfb8" if theme_mode == "dark" else "#725619"
    warning_border = "#7a6740" if theme_mode == "dark" else "#c9ac6a"
    warning_background = "#30291b" if theme_mode == "dark" else "#f4ead1"
    return f"""
QDialog {{ background: {colors['background']}; color: {colors['text']};
  font-family: "Malgun Gothic", "Segoe UI"; font-size: 13px; }}
QFrame#WindowTitleBar {{ background: {colors['chrome']}; border: 0; border-bottom: 1px solid {colors['border']}; }}
QFrame#WindowTitleBar QLabel#AppTitle {{ color: {colors['text']}; font-size: 16px; font-weight: 900; }}
QLabel#AppLogo, QWidget#TitleBarCenter, QWidget#TitleBarActions {{ background: transparent; border: 0; }}
QFrame#WindowControlGroup {{ background: {colors['raised']}; border: 1px solid {colors['border']}; border-radius: 12px; }}
QFrame#TitleBarControlDivider {{ background: {colors['border']}; border: 0; }}
QFrame#SetupHeader {{ background: {colors['chrome']}; border-bottom: 1px solid {colors['border']}; }}
QLabel#SetupBrand {{ color: {colors['text']}; font-size: 17px; font-weight: 800; }}
QLabel#SetupStep {{ color: {colors['faint']}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
QLabel#SetupStepCount {{ color: {colors['muted']}; background: {colors['card']}; border: 1px solid {colors['border']};
  border-radius: 10px; padding: 5px 10px; font-size: 10px; font-weight: 800; }}
QLabel#SetupTitle {{ color: {colors['text']}; font-size: 22px; font-weight: 800; }}
QLabel#SetupDescription {{ color: {colors['muted']}; font-size: 11px; }}
QLabel#SetupProgressDetail {{ color: {colors['faint']}; font-size: 10px; font-weight: 700; }}
QFrame#SetupCard, QFrame#SetupPreview {{ background: {colors['card']}; border: 1px solid {colors['border']}; border-radius: 14px; }}
QLabel#SetupFieldLabel {{ color: {colors['muted']}; font-size: 10px; font-weight: 800; }}
QLabel#SetupPathPreview {{ color: {colors['muted']}; font-size: 10px; }}
QLineEdit#SetupPathEdit {{ color: {colors['text']}; background: {input_color}; border: 1px solid {colors['button_border']};
  border-radius: 9px; min-height: 36px; padding: 0 11px; selection-background-color: {colors['selection']}; }}
QLineEdit#SetupPathEdit:focus {{ border-color: {colors['focus']}; }}
QPushButton#SetupPrimaryButton, QPushButton#SetupSecondaryButton, QPushButton#SetupBrowseButton {{
  min-height: 34px; padding: 0 15px; border-radius: 9px; font-weight: 800; }}
QPushButton#SetupPrimaryButton {{ color: {colors['accent_text']}; background: {colors['accent']}; border: 1px solid {colors['accent']}; }}
QPushButton#SetupPrimaryButton:hover {{ background: {colors['active_hover']}; }}
QPushButton#SetupPrimaryButton:pressed {{ background: {colors['active_pressed']}; }}
QPushButton#SetupSecondaryButton, QPushButton#SetupBrowseButton {{ color: {colors['text']}; background: {colors['card']};
  border: 1px solid {colors['button_border']}; }}
QPushButton#SetupSecondaryButton:hover, QPushButton#SetupBrowseButton:hover {{ background: {colors['hover']}; }}
QPushButton#SetupPrimaryButton:disabled, QPushButton#SetupSecondaryButton:disabled,
QPushButton#SetupBrowseButton:disabled {{ color: {colors['faint']}; background: {colors['card']};
  border-color: {colors['border']}; }}
QLabel#SetupError {{ color: {colors['source_youtube_text']}; background: {colors['source_youtube_background']};
  border: 1px solid {colors['source_youtube_border']};
  border-radius: 9px; padding: 8px 11px; }}
QProgressBar#SetupProgress {{ min-height: 5px; max-height: 5px; border: 0; border-radius: 2px; background: {colors['raised']}; }}
QProgressBar#SetupProgress::chunk {{ background: {colors['accent']}; border-radius: 2px; }}
QFrame#SetupStageStrip {{ background: {colors['chrome']}; border: 1px solid {colors['border']}; border-radius: 10px; }}
QLabel#SetupStageBadge {{ color: {colors['faint']}; background: transparent; border: 0; border-radius: 7px;
  min-height: 25px; font-size: 9px; font-weight: 700; }}
QLabel#SetupStageBadge[state='active'] {{ color: {colors['tab_active_text']}; background: {colors['tab_active']}; }}
QLabel#SetupStageBadge[state='complete'] {{ color: {colors['source_output_text']}; }}
QFrame#DiagnosticRow {{ background: {colors['card']}; border: 1px solid {colors['border']}; border-radius: 11px; }}
QFrame#DiagnosticRow[status='fail'] {{ border-color: #8a4437; }}
QFrame#DiagnosticRow[status='warning'] {{ border-color: #7a6740; }}
QFrame#DiagnosticRow[status='required'] {{ border-color: {warning_border}; }}
QFrame#DiagnosticRow[status='running'] {{ border-color: {colors['focus']}; }}
QLabel#DiagnosticTitle {{ color: {colors['text']}; font-size: 11px; font-weight: 800; }}
QLabel#DiagnosticDetail {{ color: {colors['faint']}; font-size: 9px; }}
QLabel#DiagnosticStatus {{ color: {colors['focus']}; background: {input_color}; border: 1px solid {colors['border']};
  border-radius: 8px; min-width: 68px; padding: 4px 7px; font-size: 9px; font-weight: 800; }}
QLabel#DiagnosticStatus[status='pass'] {{ color: {colors['source_output_text']};
  border-color: {colors['source_output_border']}; background: {colors['source_output_background']}; }}
QLabel#DiagnosticStatus[status='warning'] {{ color: {warning_text}; border-color: {warning_border};
  background: {warning_background}; }}
QLabel#DiagnosticStatus[status='required'] {{ color: {warning_text}; border-color: {warning_border};
  background: {warning_background}; }}
QLabel#DiagnosticStatus[status='running'] {{ color: {colors['text']}; border-color: {colors['focus']};
  background: {colors['tab_active']}; }}
QLabel#DiagnosticStatus[status='skipped'], QLabel#DiagnosticStatus[status='pending'] {{
  color: {colors['faint']}; border-color: {colors['border']}; background: {colors['raised']}; }}
QLabel#DiagnosticStatus[status='fail'] {{ color: {colors['source_youtube_text']};
  border-color: {colors['source_youtube_border']}; background: {colors['source_youtube_background']}; }}
"""
