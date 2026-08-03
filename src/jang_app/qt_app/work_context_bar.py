from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.work_song_selector import WorkSongSelector
from jang_app.services.work_context import WorkContextDisplay


class WorkContextBar(QFrame):
    song_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkContextBar")
        self.setFixedHeight(52)
        self._display = WorkContextDisplay(is_active=False)

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

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("WorkDetail")
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.detail_label.setFixedWidth(180)

        self.state_label = QLabel("")
        self.state_label.setObjectName("WorkStateBadge")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setFixedWidth(86)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(10)
        layout.addWidget(self.work_badge, 0)
        layout.addWidget(self.source_badge, 0)
        layout.addWidget(self.song_combo, 1)
        layout.addWidget(self.detail_label, 0)
        layout.addWidget(self.state_label, 0)
        self.set_songs(())
        self.set_display(WorkContextDisplay(is_active=False))

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
        self.setVisible(True)
        self.source_badge.setVisible(display.is_active)
        self.detail_label.setVisible(display.is_active and bool(display.detail_label))
        self.state_label.setVisible(display.is_active and bool(display.state_label))
        if not display.is_active:
            return

        set_translated_text(self.source_badge, display.source_label)
        self.source_badge.setProperty("sourceType", display.source_type)
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        self.detail_label.setText(display.detail_label)
        self.detail_label.setToolTip(display.detail_label)
        set_translated_text(self.state_label, display.state_label)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.song_combo.apply_language()
        self.set_display(self._display)
