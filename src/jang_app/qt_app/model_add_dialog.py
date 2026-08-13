from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.i18n import tr


class ModelAddAction(StrEnum):
    CREATE = "create"
    IMPORT = "import"


class ModelImportSource(StrEnum):
    INFERENCE_FILE = "inference_file"
    RVC_FOLDER = "rvc_folder"
    DRIVE_LINK = "drive_link"


class ModelImportMode(StrEnum):
    MANAGED = "managed"
    LINKED = "linked"


@dataclass(frozen=True)
class ModelAddRequest:
    action: ModelAddAction
    source: ModelImportSource = ModelImportSource.INFERENCE_FILE
    mode: ModelImportMode = ModelImportMode.MANAGED
    link: str = ""


class ModelAddDialog(AppDialog):
    def __init__(
        self,
        logo_path: Path,
        *,
        theme_mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(tr("Add Model"), logo_path, theme_mode=theme_mode, parent=parent)
        self.setFixedSize(640, 490)
        self.setStyleSheet(build_stylesheet(theme_mode))
        self._request: ModelAddRequest | None = None

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_action_page())
        self.stack.addWidget(self._build_import_page())
        self.stack.addWidget(self._build_drive_page())
        self.content_layout.addWidget(self.stack)

    @classmethod
    def get_request(
        cls,
        parent: QWidget,
        logo_path: Path,
        *,
        theme_mode: str,
    ) -> ModelAddRequest | None:
        dialog = cls(logo_path, theme_mode=theme_mode, parent=parent)
        return dialog.request() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def request(self) -> ModelAddRequest | None:
        return self._request

    def _build_action_page(self) -> QWidget:
        page, layout = _dialog_page(
            tr("Add Model"),
            tr("Create a model for training or bring in an existing RVC model."),
        )
        self.create_button = _choice_button(
            tr("Create New Model\nStart with an empty managed model and add training material."),
        )
        self.create_button.clicked.connect(self._accept_create)
        self.existing_button = _choice_button(
            tr("Import Existing Model\nUse an inference file or import a complete RVC folder."),
        )
        self.existing_button.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.drive_button = _choice_button(
            tr("Import Drive Link\nDownload a JJZero RVC model or model-work package shared through Google Drive."),
        )
        self.drive_button.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        cancel = FeedbackButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)

        layout.addWidget(self.create_button)
        layout.addWidget(self.existing_button)
        layout.addWidget(self.drive_button)
        layout.addStretch(1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        layout.addLayout(footer)
        return page

    def _build_drive_page(self) -> QWidget:
        page, layout = _dialog_page(
            tr("Import Drive Link"),
            tr("Paste a public JJZero share link from Google Drive."),
        )
        self.drive_link_edit = QLineEdit()
        self.drive_link_edit.setObjectName("ModelAddDriveLink")
        self.drive_link_edit.setPlaceholderText(tr("Google Drive file link"))
        self.drive_link_edit.textChanged.connect(
            lambda value: self.drive_import_button.setEnabled(bool(value.strip()))
        )
        back = FeedbackButton(tr("Back"))
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        cancel = FeedbackButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.drive_import_button = FeedbackButton(tr("Download and Import"))
        self.drive_import_button.setObjectName("PrimaryButton")
        self.drive_import_button.setEnabled(False)
        self.drive_import_button.clicked.connect(self._accept_drive_import)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(back)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.drive_import_button)
        layout.addWidget(self.drive_link_edit)
        layout.addStretch(1)
        layout.addLayout(footer)
        return page

    def _build_import_page(self) -> QWidget:
        page, layout = _dialog_page(
            tr("Import Existing Model"),
            tr("An inference PTH is enough for conversion. An INDEX is optional."),
        )

        source_label = QLabel(tr("Source"))
        source_label.setObjectName("CardTitle")
        self.file_source_button = _option_button(
            tr("Inference File (.pth)\nFast setup for conversion; a matching INDEX is detected automatically."),
        )
        self.folder_source_button = _option_button(
            tr("RVC Model Folder\nScan inference files, INDEX files, and G/D checkpoints."),
        )
        self.file_source_button.setChecked(True)
        source_group = QButtonGroup(self)
        source_group.setExclusive(True)
        source_group.addButton(self.file_source_button)
        source_group.addButton(self.folder_source_button)

        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        source_row.addWidget(self.file_source_button, 1)
        source_row.addWidget(self.folder_source_button, 1)

        storage_label = QLabel(tr("Storage"))
        storage_label.setObjectName("CardTitle")
        self.managed_mode_button = _option_button(
            tr("Copy into JJZero\nKeep a managed copy that remains available if the source moves."),
        )
        self.linked_mode_button = _option_button(
            tr("Link Original\nUse files in place without copying or modifying them."),
        )
        self.managed_mode_button.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        mode_group.addButton(self.managed_mode_button)
        mode_group.addButton(self.linked_mode_button)

        storage_row = QHBoxLayout()
        storage_row.setSpacing(10)
        storage_row.addWidget(self.managed_mode_button, 1)
        storage_row.addWidget(self.linked_mode_button, 1)

        back = FeedbackButton(tr("Back"))
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        cancel = FeedbackButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.import_button = FeedbackButton(tr("Choose Source"))
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.clicked.connect(self._accept_import)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(back)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.import_button)

        layout.addWidget(source_label)
        layout.addLayout(source_row)
        layout.addWidget(storage_label)
        layout.addLayout(storage_row)
        layout.addStretch(1)
        layout.addLayout(footer)
        return page

    def _accept_create(self) -> None:
        self._request = ModelAddRequest(ModelAddAction.CREATE)
        self.accept()

    def _accept_import(self) -> None:
        source = (
            ModelImportSource.INFERENCE_FILE
            if self.file_source_button.isChecked()
            else ModelImportSource.RVC_FOLDER
        )
        mode = (
            ModelImportMode.MANAGED
            if self.managed_mode_button.isChecked()
            else ModelImportMode.LINKED
        )
        self._request = ModelAddRequest(ModelAddAction.IMPORT, source, mode)
        self.accept()

    def _accept_drive_import(self) -> None:
        link = self.drive_link_edit.text().strip()
        if not link:
            return
        self._request = ModelAddRequest(
            ModelAddAction.IMPORT,
            ModelImportSource.DRIVE_LINK,
            ModelImportMode.MANAGED,
            link,
        )
        self.accept()


def _dialog_page(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
    page = QFrame()
    page.setObjectName("AppDialogBody")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("SectionTitle")
    detail = QLabel(description)
    detail.setObjectName("MutedText")
    detail.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(detail)
    layout.addSpacing(4)
    return page, layout


def _choice_button(text: str) -> FeedbackButton:
    button = FeedbackButton(text)
    button.setObjectName("ModelAddChoice")
    button.setFixedHeight(76)
    return button


def _option_button(text: str) -> FeedbackButton:
    button = FeedbackButton(text)
    button.setObjectName("ModelAddOption")
    button.setCheckable(True)
    button.setFixedHeight(82)
    return button
