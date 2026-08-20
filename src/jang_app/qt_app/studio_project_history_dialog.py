from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.i18n import tr
from jang_app.services.studio_project import StudioProjectRevision


_CURRENT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class StudioProjectHistoryDialog(AppDialog):
    def __init__(
        self,
        revisions: tuple[StudioProjectRevision, ...],
        logo_path: Path,
        *,
        theme_mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            tr("Project History"),
            logo_path,
            theme_mode=theme_mode,
            parent=parent,
        )
        self.setFixedSize(620, 520)
        self.setStyleSheet(build_stylesheet(theme_mode))
        self.revision: int | None = None

        body = QFrame()
        body.setObjectName("AppDialogBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)

        heading = QLabel(tr("Project History"))
        heading.setObjectName("SectionTitle")
        detail = QLabel(
            tr(
                "Restore an earlier Studio timeline. The current version remains in history."
            )
        )
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        self.revision_list = QListWidget()
        self.revision_list.setObjectName("StudioProjectHistoryList")
        self.revision_list.itemDoubleClicked.connect(lambda _item: self._restore())
        for index, revision in enumerate(revisions):
            title = tr("Revision {revision}").format(revision=revision.revision)
            if index == 0:
                title = f"{title}  ·  {tr('Current')}"
            item = QListWidgetItem(
                "\n".join(
                    (
                        title,
                        f"{_display_timestamp(revision.created_at)}  ·  "
                        + tr("{tracks} tracks · {clips} clips").format(
                            tracks=revision.track_count,
                            clips=revision.clip_count,
                        ),
                    )
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, revision.revision)
            item.setData(_CURRENT_ROLE, index == 0)
            self.revision_list.addItem(item)
        empty = QLabel(tr("No saved revisions yet."))
        empty.setObjectName("MutedText")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setVisible(not revisions)

        cancel_button = FeedbackButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        self.restore_button = FeedbackButton(tr("Restore Revision"))
        self.restore_button.setObjectName("PrimaryButton")
        self.restore_button.clicked.connect(self._restore)
        self.revision_list.itemSelectionChanged.connect(self._sync_restore_button)
        if revisions:
            self.revision_list.setCurrentRow(0)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(cancel_button)
        actions.addWidget(self.restore_button)

        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addWidget(self.revision_list, 1)
        layout.addWidget(empty, 1)
        layout.addLayout(actions)
        self.content_layout.addWidget(body)
        self._sync_restore_button()

    def _sync_restore_button(self) -> None:
        item = self.revision_list.currentItem()
        self.restore_button.setEnabled(
            item is not None and item.data(_CURRENT_ROLE) is not True
        )

    def _restore(self) -> None:
        item = self.revision_list.currentItem()
        if item is None or item.data(_CURRENT_ROLE) is True:
            return
        self.revision = int(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    @classmethod
    def choose(
        cls,
        parent: QWidget,
        revisions: tuple[StudioProjectRevision, ...],
        logo_path: Path,
        *,
        theme_mode: str,
    ) -> int | None:
        dialog = cls(revisions, logo_path, theme_mode=theme_mode, parent=parent)
        return dialog.revision if dialog.exec() == QDialog.DialogCode.Accepted else None


def _display_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value or "-"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
