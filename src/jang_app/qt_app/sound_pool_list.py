from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.sound_pool_theme import apply_sound_pool_theme
from jang_app.qt_app.widgets import attach_transparent_scroll_widget


class SoundPoolList(QFrame):
    """Shared scrollable list surface for selectable sound cards."""

    selected = Signal(str)

    def __init__(
        self,
        *,
        object_name: str = "SoundPoolList",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cards: dict[str, SoundPoolItemCard] = {}
        self._theme_mode = "white"

        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.title_label = QLabel()
        self.title_label.setObjectName("SoundPoolListTitle")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("SoundPoolListCount")
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(6)
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addWidget(self.count_label)
        self.header_layout.addStretch(1)

        self.content = QWidget()
        self.content.setObjectName("SoundPoolListContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(7)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("SoundPoolListEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("SoundPoolListScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        attach_transparent_scroll_widget(self.scroll, self.content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(self.header_layout)
        layout.addWidget(self.scroll, 1)
        apply_sound_pool_theme(self, self._theme_mode)

    @property
    def cards(self) -> dict[str, SoundPoolItemCard]:
        return self._cards

    def set_copy(self, title: str, empty_text: str) -> None:
        self.title_label.setText(title)
        self.empty_label.setText(empty_text)

    def set_cards(
        self,
        cards: tuple[SoundPoolItemCard, ...],
        selected_key: str,
    ) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                if widget is not self.empty_label:
                    widget.deleteLater()
        self._cards.clear()
        for card in cards:
            card.setParent(self.content)
            card.activated.connect(self.selected.emit)
            card.set_selected(card.card_id == selected_key)
            self._cards[card.card_id] = card
            self.content_layout.addWidget(card)
        self.empty_label.setVisible(not cards)
        if not cards:
            self.content_layout.addWidget(self.empty_label, 1)
        self.content_layout.addStretch(1)
        self.count_label.setText(str(len(cards)))

    def set_selected(self, selected_key: str) -> None:
        for key, card in self._cards.items():
            card.set_selected(key == selected_key)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        apply_sound_pool_theme(self, theme_mode)
        for card in self._cards.values():
            card.set_theme_mode(theme_mode)
