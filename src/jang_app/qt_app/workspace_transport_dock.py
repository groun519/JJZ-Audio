from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout

from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.work_song_selector import WorkSongSelector


class WorkspaceTransportDock(QFrame):
    song_changed = Signal(str)
    play_toggled = Signal()
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkspaceTransportDock")
        self.setFixedHeight(84)

        self.song_combo = WorkSongSelector()
        self.song_combo.song_changed.connect(self.song_changed.emit)

        self.transport = TransportControls(self.song_combo)
        self.transport.play_toggled.connect(self.play_toggled.emit)
        self.transport.seek_requested.connect(self.seek_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.transport, 0)
        self.clear()

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self.song_combo.set_songs(songs, selected_id)

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        self.song_combo.select_song(song_id, emit=emit)

    def selected_song_id(self) -> str:
        return self.song_combo.selected_song_id()

    def has_song(self, song_id: str) -> bool:
        return self.song_combo.has_song(song_id)

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
        self.song_combo.apply_language()
        self.transport.apply_language()
