from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.widgets import attach_transparent_scroll_widget
from jang_app.services.i18n import tr


STUDIO_EFFECT_MIME = "application/x-jjzero-studio-effect"


class StudioFxCard(QFrame):
    def __init__(self, effect_kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.effect_kind = effect_kind
        self.setObjectName("StudioFxCard")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_origin = QPoint()

        self.icon_label = QLabel("RV")
        self.icon_label.setObjectName("StudioFxCardIcon")
        self.name_label = QLabel()
        self.name_label.setObjectName("StudioFxCardName")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("StudioFxCardDetail")

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(2)
        copy.addWidget(self.name_label)
        copy.addWidget(self.detail_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(10)
        layout.addWidget(self.icon_label)
        layout.addLayout(copy, 1)
        self.apply_language()

    def apply_language(self) -> None:
        self.name_label.setText(tr("Reverb"))
        self.detail_label.setText(tr("Room and ambience"))
        self.setToolTip(tr("Drag onto a timeline clip to add Reverb."))

    def mime_data(self) -> QMimeData:
        mime = QMimeData()
        mime.setData(STUDIO_EFFECT_MIME, self.effect_kind.encode("utf-8"))
        return mime

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        distance = (event.position().toPoint() - self._drag_origin).manhattanLength()
        if not event.buttons() & Qt.MouseButton.LeftButton or distance < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)
        drag = QDrag(self)
        drag.setMimeData(self.mime_data())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)


class StudioFxPool(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StudioFxPool")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(120)

        self.title_label = QLabel("FX")
        self.title_label.setObjectName("SectionTitle")
        self.count_label = QLabel("1")
        self.count_label.setObjectName("StudioSoundCount")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)

        self.content = QWidget()
        self.content.setObjectName("StudioFxPoolContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards = {"reverb": StudioFxCard("reverb", self.content)}
        content_layout.addWidget(self.cards["reverb"])

        self.scroll = QScrollArea()
        self.scroll.setObjectName("StudioFxPoolScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        attach_transparent_scroll_widget(self.scroll, self.content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.scroll, 1)

    def set_theme_mode(self, _theme_mode: str) -> None:
        self.update()

    def apply_language(self) -> None:
        self.title_label.setText("FX")
        for card in self.cards.values():
            card.apply_language()
