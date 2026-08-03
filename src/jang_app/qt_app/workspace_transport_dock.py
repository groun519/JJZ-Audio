from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.work_song_selector import WorkSongSelector
from jang_app.services.work_context import WorkContextDisplay


class WorkspaceTransportDock(QFrame):
    song_changed = Signal(str)
    play_toggled = Signal()
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkspaceTransportDock")
        self.setFixedHeight(94)
        self._display = WorkContextDisplay(is_active=False)
        self._queue_context = ""
        self._queue_title = ""

        self.work_badge = QLabel("WORK")
        self.work_badge.setObjectName("WorkBadge")
        self.work_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.work_badge.setFixedWidth(54)

        self.source_badge = QLabel("")
        self.source_badge.setObjectName("WorkSourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(48)

        self.song_combo = WorkSongSelector()
        self.song_combo.song_changed.connect(self.song_changed.emit)

        self.state_label = QLabel("")
        self.state_label.setObjectName("WorkStateBadge")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setFixedWidth(86)

        divider = QFrame()
        divider.setObjectName("WorkspaceTransportDivider")
        divider.setFixedSize(1, 24)

        self.context_label = QLabel("")
        self.context_label.setObjectName("PlayerContext")
        self.context_label.setFixedWidth(72)
        self.context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("")
        self.title_label.setObjectName("PlayerTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)
        info_layout.addWidget(self.work_badge, 0)
        info_layout.addWidget(self.source_badge, 0)
        info_layout.addWidget(self.song_combo, 3)
        info_layout.addWidget(self.state_label, 0)
        info_layout.addWidget(divider, 0)
        info_layout.addWidget(self.context_label, 0)
        info_layout.addWidget(self.title_label, 2)

        self.transport = TransportControls(button_size=34)
        self.transport.play_toggled.connect(self.play_toggled.emit)
        self.transport.seek_requested.connect(self.seek_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        layout.addLayout(info_layout)
        layout.addWidget(self.transport, 0)
        self.set_display(WorkContextDisplay(is_active=False))
        self.clear()

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self.song_combo.set_songs(songs, selected_id)

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        self.song_combo.select_song(song_id, emit=emit)

    def selected_song_id(self) -> str:
        return self.song_combo.selected_song_id()

    def has_song(self, song_id: str) -> bool:
        return self.song_combo.has_song(song_id)

    def set_display(self, display: WorkContextDisplay) -> None:
        self._display = display
        self.source_badge.setVisible(display.is_active)
        self.state_label.setVisible(display.is_active and bool(display.state_label))
        if not display.is_active:
            return
        set_translated_text(self.source_badge, display.source_label)
        self.source_badge.setProperty("sourceType", display.source_type)
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        set_translated_text(self.state_label, display.state_label)

    def set_queue(self, context: str, title: str, duration_ms: int) -> None:
        self._queue_context = context
        self._queue_title = title.strip()
        set_translated_text(self.context_label, context)
        self.context_label.setVisible(bool(context))
        self.title_label.setText(self._queue_title)
        self.title_label.setToolTip(self._queue_title)
        self.transport.set_duration(duration_ms)

    def clear(self) -> None:
        self._queue_context = ""
        self._queue_title = ""
        self.context_label.clear()
        self.context_label.hide()
        set_translated_text(self.title_label, "No sound selected")
        self.title_label.setToolTip("")
        self.transport.clear()

    def set_playing(self, is_playing: bool) -> None:
        self.transport.set_playing(is_playing)

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        self.transport.set_position(position_ms, duration_ms)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.transport.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.song_combo.apply_language()
        self.transport.apply_language()
        self.set_display(self._display)
        if self._queue_context:
            set_translated_text(self.context_label, self._queue_context)
        if not self._queue_title:
            set_translated_text(self.title_label, "No sound selected")
