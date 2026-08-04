from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.widgets import SvgIconButton


FLOATING_PLAYER_WIDTH = 460
FLOATING_PLAYER_HEIGHT = 94


class FloatingPlaybackPanel(QFrame):
    play_toggled = Signal()
    seek_requested = Signal(int)
    dismiss_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FloatingPlaybackPanel")
        self.setFixedSize(FLOATING_PLAYER_WIDTH, FLOATING_PLAYER_HEIGHT)

        self.title_label = OverflowTextLabel(
            object_name="FloatingPlaybackTitle",
            fixed_height=20,
        )
        self.close_button = SvgIconButton("close", size=28)
        self.close_button.setObjectName("FloatingPlaybackClose")
        set_translated_tooltip(self.close_button, "Close preview")
        self.close_button.clicked.connect(self.dismiss_requested.emit)

        header = QWidget()
        header.setObjectName("FloatingPlaybackHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.close_button, 0)

        self.transport = TransportControls()
        self.transport.setObjectName("FloatingPlaybackTransport")
        self.transport.play_toggled.connect(self.play_toggled.emit)
        self.transport.seek_requested.connect(self.seek_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(6)
        layout.addWidget(header)
        layout.addWidget(self.transport)
        self.clear()

    def set_queue(self, title: str, duration_ms: int) -> None:
        self.title_label.setText(title)
        self.transport.set_position(0, duration_ms)

    def clear(self) -> None:
        self.title_label.setText("")
        self.transport.clear()

    def set_playing(self, is_playing: bool) -> None:
        self.transport.set_playing(is_playing)

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        self.transport.set_position(position_ms, duration_ms)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.close_button.set_theme_mode(theme_mode)
        self.transport.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_tooltip(self.close_button, "Close preview")
        self.transport.apply_language()
