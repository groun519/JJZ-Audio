from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.app_dialog import AppDialog
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.i18n import tr


EFFECT_SCOPE_CLIP = "clip"
EFFECT_SCOPE_SOURCE = "source"


class StudioEffectScopeDialog(AppDialog):
    def __init__(
        self,
        sibling_count: int,
        logo_path: Path,
        *,
        theme_mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            tr("Apply effect"),
            logo_path,
            theme_mode=theme_mode,
            parent=parent,
        )
        self.setFixedSize(540, 350)
        self.setStyleSheet(build_stylesheet(theme_mode))
        self.scope: str | None = None

        body = QFrame()
        body.setObjectName("AppDialogBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(10)

        heading = QLabel(tr("Apply effect"))
        heading.setObjectName("SectionTitle")
        detail = QLabel(
            tr(
                "This audio is used in {count} clips. Choose how broadly to apply the effect."
            ).format(count=sibling_count)
        )
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        clip_button = FeedbackButton(tr("Selected clip only"))
        clip_button.setMinimumHeight(46)
        clip_button.clicked.connect(lambda: self._accept_scope(EFFECT_SCOPE_CLIP))
        clip_detail = QLabel(tr("Only the clip where the effect was dropped will change."))
        clip_detail.setObjectName("MutedText")

        source_button = FeedbackButton(tr("All pieces from this audio"))
        source_button.setObjectName("PrimaryButton")
        source_button.setMinimumHeight(46)
        source_button.setDefault(True)
        source_button.clicked.connect(lambda: self._accept_scope(EFFECT_SCOPE_SOURCE))
        source_detail = QLabel(
            tr("The effect stays linked when edited, bypassed, removed, or split again.")
        )
        source_detail.setObjectName("MutedText")
        source_detail.setWordWrap(True)

        cancel_button = FeedbackButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(cancel_button)

        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addSpacing(4)
        layout.addWidget(clip_button)
        layout.addWidget(clip_detail)
        layout.addSpacing(4)
        layout.addWidget(source_button)
        layout.addWidget(source_detail)
        layout.addStretch(1)
        layout.addLayout(actions)
        self.content_layout.addWidget(body)

    def _accept_scope(self, scope: str) -> None:
        self.scope = scope
        self.accept()

    @classmethod
    def choose(
        cls,
        parent: QWidget,
        sibling_count: int,
        logo_path: Path,
        *,
        theme_mode: str,
    ) -> str | None:
        dialog = cls(
            sibling_count,
            logo_path,
            theme_mode=theme_mode,
            parent=parent,
        )
        return dialog.scope if dialog.exec() == QDialog.DialogCode.Accepted else None
