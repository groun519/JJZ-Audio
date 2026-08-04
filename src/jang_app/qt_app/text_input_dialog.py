from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton


class TextInputDialog(AppDialog):
    def __init__(
        self,
        title: str,
        field_label: str,
        logo_path: Path,
        *,
        theme_mode: str,
        accept_label: str,
        cancel_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, logo_path, theme_mode=theme_mode, parent=parent)
        self.setFixedSize(480, 236)
        self.setStyleSheet(build_stylesheet(theme_mode))

        body = QFrame()
        body.setObjectName("AppDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        label = QLabel(field_label)
        label.setObjectName("MutedText")
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("AppDialogInput")
        self.input_edit.textChanged.connect(self._update_accept_state)
        self.input_edit.returnPressed.connect(self._accept_if_valid)

        self.cancel_button = FeedbackButton(cancel_label)
        self.cancel_button.clicked.connect(self.reject)
        self.accept_button = FeedbackButton(accept_label)
        self.accept_button.setObjectName("PrimaryButton")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._accept_if_valid)
        self.accept_button.setEnabled(False)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.accept_button)

        body_layout.addWidget(heading)
        body_layout.addWidget(label)
        body_layout.addWidget(self.input_edit)
        body_layout.addStretch(1)
        body_layout.addLayout(actions)
        self.content_layout.addWidget(body)

    @classmethod
    def get_text(
        cls,
        parent: QWidget,
        title: str,
        field_label: str,
        logo_path: Path,
        *,
        theme_mode: str,
        accept_label: str,
        cancel_label: str,
    ) -> tuple[str, bool]:
        dialog = cls(
            title,
            field_label,
            logo_path,
            theme_mode=theme_mode,
            accept_label=accept_label,
            cancel_label=cancel_label,
            parent=parent,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.text_value(), accepted

    def text_value(self) -> str:
        return self.input_edit.text().strip()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.input_edit.setFocus()

    def _update_accept_state(self, text: str) -> None:
        self.accept_button.setEnabled(bool(text.strip()))

    def _accept_if_valid(self) -> None:
        if self.text_value():
            self.accept()
