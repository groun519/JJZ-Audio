from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language
from jang_app.qt_app.widgets import ScrollSafeComboBox
from jang_app.services.i18n import tr


class SelectedSongCard(QFrame):
    song_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._loading = False

        title = QLabel("Selected Song")
        title.setObjectName("MutedText")

        self.combo = ScrollSafeComboBox()
        self.combo.currentIndexChanged.connect(self._emit_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(self.combo)

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self._loading = True
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Select"), "")
        for song_id, title in songs:
            self.combo.addItem(title, song_id)
        index = self.combo.findData(selected_id)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.blockSignals(False)
        self._loading = False

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        index = self.combo.findData(song_id)
        was_blocked = self.combo.blockSignals(not emit)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.blockSignals(was_blocked)

    def selected_song_id(self) -> str:
        value = self.combo.currentData()
        return str(value) if value else ""

    def apply_language(self) -> None:
        apply_widget_language(self)
        if self.combo.count() > 0:
            self.combo.setItemText(0, tr("Select"))

    def _emit_selection(self, _index: int) -> None:
        if not self._loading:
            self.song_changed.emit(self.selected_song_id())
