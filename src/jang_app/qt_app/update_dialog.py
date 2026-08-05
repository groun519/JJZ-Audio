from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.services.app_update import UpdatePlan
from jang_app.services.i18n import tr


class UpdateDialog(AppDialog):
    download_requested = Signal()
    install_requested = Signal()

    def __init__(
        self,
        plan: UpdatePlan,
        logo_path: Path,
        *,
        current_version: str,
        theme_mode: str,
        parent=None,
    ) -> None:
        super().__init__(
            tr("JJZero Audio Update"),
            logo_path,
            theme_mode=theme_mode,
            parent=parent,
        )
        self._plan = plan
        self._is_downloading = False
        self.setMinimumWidth(520)
        self.setStyleSheet(build_stylesheet(theme_mode))
        self._build_ui(current_version)

    def _build_ui(self, current_version: str) -> None:
        body = QFrame()
        body.setObjectName("Panel")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel(tr("Update Available"))
        title.setObjectName("SectionTitle")
        versions = QLabel(self._version_text(current_version))
        versions.setObjectName("MutedText")
        detail = QLabel(self._detail_text())
        detail.setObjectName("BodyText")
        detail.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setObjectName("MutedText")
        self.status.setWordWrap(True)
        self.status.hide()

        self.later_button = QPushButton(tr("Later"))
        self.later_button.clicked.connect(self.reject)
        self.primary_button = QPushButton(tr("Download Update"))
        self.primary_button.setProperty("variant", "primary")
        self.primary_button.clicked.connect(self.download_requested.emit)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.later_button)
        actions.addWidget(self.primary_button)

        layout.addWidget(title)
        layout.addWidget(versions)
        layout.addWidget(detail)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(actions)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.addWidget(body)

    def set_downloading(self) -> None:
        self._is_downloading = True
        self.primary_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText(tr("Downloading and verifying update..."))
        self.status.show()

    def set_running(self, is_running: bool) -> None:
        if is_running:
            self.set_downloading()
        else:
            self._is_downloading = False

    def set_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))

    def set_download_failed(self, message: str) -> None:
        self.primary_button.setEnabled(True)
        self.later_button.setEnabled(True)
        self.status.setText(f"{tr('Update failed')}: {message}")
        self.status.show()

    def set_ready_to_install(self) -> None:
        self.progress.setValue(100)
        self.status.setText(tr("Update verified. Restart JJZero Audio to install it."))
        self.status.show()
        self.later_button.setEnabled(True)
        self.primary_button.setEnabled(True)
        self.primary_button.setText(tr("Restart and Install"))
        self.primary_button.clicked.disconnect()
        self.primary_button.clicked.connect(self.install_requested.emit)

    def set_installing_runtime(self) -> None:
        self._is_downloading = True
        self.primary_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText(tr("Installing AI runtime..."))
        self.status.show()

    def _detail_text(self) -> str:
        details = (
            [tr("A new application version is ready.")]
            if self._plan.application_required
            else []
        )
        if self._plan.runtime_required:
            details.append(tr("This release also updates the AI runtime."))
        if self._plan.rvc_profile_required:
            details.append(tr("The RVC runtime will be configured for the detected GPU."))
        return "\n".join(details)

    def _version_text(self, current_version: str) -> str:
        if self._plan.application_required:
            return f"{current_version}  ->  {self._plan.release.version}"
        if self._plan.rvc_profile_required:
            return f"{tr('GPU Runtime')}  ->  {self._plan.rvc_profile.upper()}"
        runtime = self._plan.release.ai_runtime
        return f"{tr('AI Runtime')}  ->  {runtime.version if runtime is not None else ''}"

    def reject(self) -> None:
        if not self._is_downloading:
            super().reject()
