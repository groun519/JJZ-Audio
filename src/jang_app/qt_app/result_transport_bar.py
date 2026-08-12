from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout

from jang_app.qt_app.transport_controls import TransportControls


class ResultTransportBar(QFrame):
    """Compact playback controls embedded below a workspace result area."""

    play_toggled = Signal()
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ResultTransportBar")
        self.setFixedHeight(54)

        self.transport = TransportControls()
        self.transport.set_shortcut_hint("Space")
        self.transport.play_toggled.connect(self.play_toggled.emit)
        self.transport.seek_requested.connect(self.seek_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.transport, 1)

    def set_queue(self, duration_ms: int) -> None:
        self.transport.set_position(0, duration_ms)

    def clear(self) -> None:
        self.transport.clear()

    def set_playing(self, is_playing: bool) -> None:
        self.transport.set_playing(is_playing)

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        self.transport.set_position(position_ms, duration_ms)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.transport.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.transport.apply_language()
