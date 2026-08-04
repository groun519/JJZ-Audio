from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QComboBox, QCompleter, QLineEdit, QSizePolicy

from jang_app.qt_app.widgets import ScrollSafeComboBox
from jang_app.services.i18n import tr


class WorkSongSelector(ScrollSafeComboBox):
    song_changed = Signal(str)

    def __init__(
        self,
        *,
        empty_text: str = "Select work song",
        search_text: str = "Search work songs",
        object_name: str = "WorkSongCombo",
    ) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self._empty_text = empty_text
        self._search_text = search_text
        self.setEditable(True)
        self.setLineEdit(_ElidingLineEdit())
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lineEdit().setClearButtonEnabled(False)
        self.activated.connect(self._activate_index)
        self.lineEdit().returnPressed.connect(self._activate_search_text)

        completer = self.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._loading = False
        self._selected_song_id = ""
        self.currentIndexChanged.connect(self._update_current_tooltip)

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self._loading = True
        self.blockSignals(True)
        self.clear()
        self.addItem(tr(self._empty_text), "")
        self.setItemData(0, tr(self._empty_text), Qt.ItemDataRole.ToolTipRole)
        for song_id, title in songs:
            self.addItem(title, song_id)
            self.setItemData(self.count() - 1, title, Qt.ItemDataRole.ToolTipRole)
        self.blockSignals(False)
        self._loading = False
        self.select_song(selected_id)

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        index = self.findData(song_id)
        selected_index = index if index >= 0 else 0
        selected_id = str(self.itemData(selected_index) or "")
        changed = selected_id != self._selected_song_id
        self._selected_song_id = selected_id
        self.setCurrentIndex(selected_index)
        self._update_current_tooltip()
        if emit and changed:
            self.song_changed.emit(selected_id)

    def selected_song_id(self) -> str:
        return self._selected_song_id

    def has_song(self, song_id: str) -> bool:
        return self.findData(song_id) >= 0

    def apply_language(self) -> None:
        if self.count() > 0:
            self.setItemText(0, tr(self._empty_text))
            self.setItemData(0, tr(self._empty_text), Qt.ItemDataRole.ToolTipRole)
        self.lineEdit().setPlaceholderText(tr(self._search_text))
        self._update_current_tooltip()

    def showPopup(self) -> None:  # noqa: N802
        content_width = max(
            (self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())),
            default=0,
        )
        popup_width = max(
            self.width(),
            min(720, content_width + 56),
        )
        self.view().setMinimumWidth(popup_width)
        self.view().window().setMinimumWidth(popup_width)
        super().showPopup()

    def _activate_index(self, index: int) -> None:
        if self._loading or index < 0:
            return
        selected_id = str(self.itemData(index) or "")
        self._selected_song_id = selected_id
        self._update_current_tooltip()
        self.song_changed.emit(selected_id)

    def _activate_search_text(self) -> None:
        query = self.currentText().strip().casefold()
        if not query:
            self.select_song("", emit=True)
            return
        for index in range(1, self.count()):
            if self.itemText(index).strip().casefold() == query:
                song_id = str(self.itemData(index) or "")
                self.select_song(song_id, emit=True)
                return
        self.select_song(self._selected_song_id)

    def _update_current_tooltip(self, *_args) -> None:
        self.setToolTip(self.itemText(self.currentIndex()) if self.currentIndex() >= 0 else "")


class _ElidingLineEdit(QLineEdit):
    def paintEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus() or not self.text():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        content = self.contentsRect().adjusted(8, 0, -30 if self.isClearButtonEnabled() else -8, 0)
        elided = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, content.width())
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        painter.drawText(content, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
