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

_PRESET_CARD_SPECS = {
    "preset:lush": (
        "LS",
        "Lush",
        "Bloom ambience with matched vocal dynamics",
    ),
    "preset:karaoke": ("KR", "Karaoke", "Karaoke vocal ambience and echo"),
    "preset:animatronic": ("AN", "Animatronic", "Metallic machine voice chain"),
    "preset:walkie_talkie": ("WT", "Walkie-Talkie", "Narrow radio transmission chain"),
    "preset:broken_robot": ("BR", "Broken Robot", "Damaged unstable robot chain"),
}

_EFFECT_CARD_SPECS = {
    "reverb": ("RV", "Reverb", "Room and ambience"),
    "delay": ("DL", "Delay", "Rhythmic echo and repeats"),
    "doubler": ("DB", "Doubler", "Thicker and wider vocal layers"),
    "radio_filter": ("RF", "Radio Filter", "Narrow speaker tone"),
    "ring_modulator": ("RM", "Ring Modulator", "Metallic robot texture"),
    "bitcrusher": ("BT", "Bitcrusher", "Digital resolution damage"),
    "distortion": ("DS", "Distortion", "Saturation and grit"),
    "level_match": ("LM", "Level Match", "Follow the original vocal volume"),
}

_CARD_SPECS = {**_PRESET_CARD_SPECS, **_EFFECT_CARD_SPECS}


class StudioFxCard(QFrame):
    def __init__(self, payload: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.payload = payload
        self.effect_kind = payload
        self.setObjectName("StudioFxCard")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_origin = QPoint()

        self.icon_label = QLabel()
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
        icon, name, detail = _CARD_SPECS[self.payload]
        self.icon_label.setText(icon)
        self.name_label.setText(tr(name))
        self.detail_label.setText(tr(detail))
        self.setToolTip(
            tr("Drag onto a timeline clip to add this preset.")
            if self.payload.startswith("preset:")
            else tr("Drag onto a timeline clip to add this effect.")
        )

    def mime_data(self) -> QMimeData:
        mime = QMimeData()
        mime.setData(STUDIO_EFFECT_MIME, self.payload.encode("utf-8"))
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
        self.count_label = QLabel(str(len(_CARD_SPECS)))
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
        self.cards = {
            payload: StudioFxCard(payload, self.content)
            for payload in _CARD_SPECS
        }
        self.preset_label = QLabel()
        self.preset_label.setObjectName("StudioFxGroupLabel")
        self.effect_label = QLabel()
        self.effect_label.setObjectName("StudioFxGroupLabel")
        content_layout.addWidget(self.preset_label)
        for payload in _PRESET_CARD_SPECS:
            content_layout.addWidget(self.cards[payload])
        content_layout.addWidget(self.effect_label)
        for payload in _EFFECT_CARD_SPECS:
            content_layout.addWidget(self.cards[payload])

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
        self.preset_label.setText(tr("Presets"))
        self.effect_label.setText(tr("Effects"))
        for card in self.cards.values():
            card.apply_language()
