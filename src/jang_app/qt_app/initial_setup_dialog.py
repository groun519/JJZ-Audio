from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
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

from jang_app.services.app_paths import AppPaths
from jang_app.services.i18n import tr
from jang_app.services.initial_setup import (
    InitialSetupError,
    complete_initial_setup,
    persist_storage_layout,
    prepare_storage_layout,
)
from jang_app.services.system_diagnostics import (
    DiagnosticCheck,
    DiagnosticStatus,
    SystemDiagnostics,
    run_system_diagnostics,
)


class DiagnosticsWorker(QThread):
    check_ready = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self._paths = paths

    def run(self) -> None:
        try:
            result = run_system_diagnostics(self._paths, reporter=self.check_ready.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class InitialSetupDialog(QDialog):
    def __init__(
        self,
        paths: AppPaths,
        logo_path: Path,
        *,
        first_run: bool = True,
        diagnostics_worker_type: type[DiagnosticsWorker] = DiagnosticsWorker,
    ) -> None:
        super().__init__()
        self._paths = paths
        self._configured_paths = paths
        self._first_run = first_run
        self._diagnostics_worker_type = diagnostics_worker_type
        self._worker: DiagnosticsWorker | None = None
        self._diagnostics: SystemDiagnostics | None = None
        self.restart_required = False

        self.setWindowTitle(tr("First Run Setup" if first_run else "System Setup"))
        self.setWindowIcon(QIcon(str(logo_path)))
        self.setModal(True)
        self.setMinimumSize(780, 560)
        self.resize(820, 590)
        self.setStyleSheet(_SETUP_STYLESHEET)
        self._build_ui(logo_path)

    @property
    def configured_paths(self) -> AppPaths:
        return self._configured_paths

    @property
    def diagnostics(self) -> SystemDiagnostics | None:
        return self._diagnostics

    def _build_ui(self, logo_path: Path) -> None:
        header = QFrame()
        header.setObjectName("SetupHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(13)
        logo = QLabel()
        logo.setPixmap(QIcon(str(logo_path)).pixmap(38, 38))
        identity = QVBoxLayout()
        identity.setSpacing(2)
        title = QLabel("JJZero Audio")
        title.setObjectName("SetupBrand")
        self.step_label = QLabel(tr("STORAGE SETUP"))
        self.step_label.setObjectName("SetupStep")
        identity.addWidget(title)
        identity.addWidget(self.step_label)
        header_layout.addWidget(logo)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
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
        self.diagnostic_summary = QLabel(tr("Checking bundled tools and NVIDIA GPU..."))
        self.diagnostic_summary.setObjectName("SetupDescription")
        self.diagnostic_progress = QProgressBar()
        self.diagnostic_progress.setRange(0, 0)
        self.diagnostic_progress.setObjectName("SetupProgress")
        self.diagnostic_progress.hide()

        checks = (
            ("storage", "Storage"),
            ("ffmpeg", "FFmpeg"),
            ("demucs", "Demucs"),
            ("rvc_assets", "RVC Assets"),
            ("ai_runtime", "AI Runtime"),
            ("cuda", "NVIDIA GPU"),
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
        self.rerun_button.clicked.connect(self._start_diagnostics)
        self.rerun_button.hide()
        rerun_row = QHBoxLayout()
        rerun_row.addStretch(1)
        rerun_row.addWidget(self.rerun_button)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(title)
        layout.addWidget(self.diagnostic_summary)
        layout.addWidget(self.diagnostic_progress)
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
        if self._worker is not None and self._worker.isRunning():
            return
        self.stack.setCurrentIndex(0)
        self.step_label.setText(tr("STORAGE SETUP"))
        self.step_count_label.setText("01 / 02")
        self.back_button.hide()
        self.primary_button.setText(tr("Continue"))
        self.cancel_button.show()

    def _start_diagnostics(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._diagnostics = None
        for row in self.diagnostic_rows.values():
            row.set_waiting()
        self.diagnostic_summary.setText(tr("Checking bundled tools and NVIDIA GPU..."))
        self.diagnostic_progress.show()
        self.rerun_button.hide()
        self.primary_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        worker = self._diagnostics_worker_type(self._configured_paths)
        worker.setParent(self)
        worker.check_ready.connect(self._on_check_ready)
        worker.completed.connect(self._on_diagnostics_complete)
        worker.failed.connect(self._on_diagnostics_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_check_ready(self, check: object) -> None:
        if isinstance(check, DiagnosticCheck) and check.key in self.diagnostic_rows:
            self.diagnostic_rows[check.key].set_check(check)

    def _on_diagnostics_complete(self, diagnostics: object) -> None:
        if not isinstance(diagnostics, SystemDiagnostics):
            self._on_diagnostics_failed("Diagnostics returned an invalid result.")
            return
        self._diagnostics = diagnostics
        for check in diagnostics.checks:
            self._on_check_ready(check)
        if diagnostics.ready and diagnostics.has_warnings:
            summary = "Setup is usable, but the NVIDIA GPU needs attention."
        elif diagnostics.ready:
            summary = "This PC is ready for JJZero Audio."
        else:
            summary = "Some bundled components are unavailable. Rebuild or repair the installation."
        self.diagnostic_summary.setText(tr(summary))
        self.diagnostic_progress.hide()
        self.rerun_button.show()
        self.primary_button.setText(tr("Start JJZero Audio" if self._first_run else "Apply and Restart"))
        self.primary_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        if not self._first_run and self._configured_paths.workspace_anchor == self._paths.workspace_anchor:
            self.primary_button.setText(tr("Close"))

    def _on_diagnostics_failed(self, error: str) -> None:
        self._diagnostics = SystemDiagnostics(
            (DiagnosticCheck("ai_runtime", "AI Runtime", DiagnosticStatus.FAIL, error),)
        )
        self._on_check_ready(self._diagnostics.checks[0])
        self.diagnostic_summary.setText(tr("System diagnostics failed."))
        self.diagnostic_progress.hide()
        self.rerun_button.show()
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
        self.detail_label = QLabel(tr("Waiting"))
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

    def set_waiting(self) -> None:
        self.detail_label.setText(tr("Waiting"))
        self.status_label.setText("—")
        self._set_status("")

    def set_check(self, check: DiagnosticCheck) -> None:
        self.detail_label.setText(tr(check.detail))
        self.detail_label.setToolTip(check.detail)
        label = {
            DiagnosticStatus.PASS: "Ready",
            DiagnosticStatus.WARNING: "Attention",
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


def _path_preview(label: str) -> QLabel:
    preview = QLabel(label)
    preview.setObjectName("SetupPathPreview")
    preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return preview


_SETUP_STYLESHEET = """
QDialog { background: #151515; color: #ecebe7; font-family: 'Segoe UI'; }
QFrame#SetupHeader { background: #111111; border-bottom: 1px solid #383835; }
QLabel#SetupBrand { color: #ecebe7; font-size: 17px; font-weight: 800; }
QLabel#SetupStep { color: #898780; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
QLabel#SetupStepCount { color: #aaa8a1; background: #212120; border: 1px solid #383835;
  border-radius: 10px; padding: 5px 10px; font-size: 10px; font-weight: 800; }
QLabel#SetupTitle { color: #ecebe7; font-size: 22px; font-weight: 800; }
QLabel#SetupDescription { color: #aaa8a1; font-size: 11px; }
QFrame#SetupCard, QFrame#SetupPreview { background: #212120; border: 1px solid #383835; border-radius: 14px; }
QLabel#SetupFieldLabel { color: #aaa8a1; font-size: 10px; font-weight: 800; }
QLabel#SetupPathPreview { color: #aaa8a1; font-size: 10px; }
QLineEdit#SetupPathEdit { color: #ecebe7; background: #191918; border: 1px solid #484843;
  border-radius: 9px; min-height: 36px; padding: 0 11px; selection-background-color: #484843; }
QLineEdit#SetupPathEdit:focus { border-color: #898780; }
QPushButton { cursor: pointer; min-height: 34px; padding: 0 15px; border-radius: 9px; font-weight: 800; }
QPushButton#SetupPrimaryButton { color: #171717; background: #efeee9; border: 1px solid #efeee9; }
QPushButton#SetupPrimaryButton:hover { background: #d8d7d1; }
QPushButton#SetupPrimaryButton:pressed { background: #c9c8c2; }
QPushButton#SetupSecondaryButton, QPushButton#SetupBrowseButton { color: #ecebe7; background: #212120;
  border: 1px solid #484843; }
QPushButton#SetupSecondaryButton:hover, QPushButton#SetupBrowseButton:hover { background: #30302e; }
QPushButton:disabled { color: #6c6b66; background: #212120; border-color: #383835; }
QLabel#SetupError { color: #d98b78; background: #2b1e1b; border: 1px solid #6e3d34;
  border-radius: 9px; padding: 8px 11px; }
QProgressBar#SetupProgress { min-height: 5px; max-height: 5px; border: 0; border-radius: 2px; background: #272725; }
QProgressBar#SetupProgress::chunk { background: #efeee9; border-radius: 2px; }
QFrame#DiagnosticRow { background: #212120; border: 1px solid #383835; border-radius: 11px; }
QFrame#DiagnosticRow[status='fail'] { border-color: #8a4437; }
QFrame#DiagnosticRow[status='warning'] { border-color: #7a6740; }
QLabel#DiagnosticTitle { color: #ecebe7; font-size: 11px; font-weight: 800; }
QLabel#DiagnosticDetail { color: #898780; font-size: 9px; }
QLabel#DiagnosticStatus { color: #898780; background: #191918; border: 1px solid #383835;
  border-radius: 8px; min-width: 68px; padding: 4px 7px; font-size: 9px; font-weight: 800; }
QLabel#DiagnosticStatus[status='pass'] { color: #c9f0dc; border-color: #3f6b53; background: #1f3128; }
QLabel#DiagnosticStatus[status='warning'] { color: #f0dfb8; border-color: #7a6740; background: #30291b; }
QLabel#DiagnosticStatus[status='fail'] { color: #ffd4d4; border-color: #7a3a3f; background: #3a2022; }
"""
