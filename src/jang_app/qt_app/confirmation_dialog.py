from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton


class ConfirmationDialog(AppDialog):
    def __init__(
        self,
        title: str,
        message: str,
        logo_path: Path,
        *,
        theme_mode: str,
        accept_label: str,
        cancel_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, logo_path, theme_mode=theme_mode, parent=parent)
        self.setFixedSize(500, 260)
        self.setStyleSheet(build_stylesheet(theme_mode))

        body = QFrame()
        body.setObjectName("AppDialogBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        detail = QLabel(message)
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        cancel_button = FeedbackButton(cancel_label)
        cancel_button.clicked.connect(self.reject)
        accept_button = FeedbackButton(accept_label)
        accept_button.setObjectName("DangerButton")
        accept_button.setDefault(True)
        accept_button.clicked.connect(self.accept)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(cancel_button)
        actions.addWidget(accept_button)

        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addStretch(1)
        layout.addLayout(actions)
        self.content_layout.addWidget(body)

    @classmethod
    def confirm(
        cls,
        parent: QWidget,
        title: str,
        message: str,
        logo_path: Path,
        *,
        theme_mode: str,
        accept_label: str,
        cancel_label: str,
    ) -> bool:
        dialog = cls(
            title,
            message,
            logo_path,
            theme_mode=theme_mode,
            accept_label=accept_label,
            cancel_label=cancel_label,
            parent=parent,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted
