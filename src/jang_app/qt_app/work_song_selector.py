from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QStyle, QStyleOptionComboBox, QStylePainter, QSizePolicy

from jang_app.qt_app.widgets import ScrollSafeComboBox
from jang_app.services.i18n import tr


class WorkSongSelector(ScrollSafeComboBox):
    song_changed = Signal(str)

    def __init__(
        self,
        *,
        empty_text: str = "Select work song",
        object_name: str = "WorkSongCombo",
    ) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self._empty_text = empty_text
        self.setEditable(False)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.activated.connect(self._activate_index)

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
        self._update_current_tooltip()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        option.currentText = self.fontMetrics().elidedText(
            option.currentText,
            Qt.TextElideMode.ElideRight,
            max(0, text_rect.width() - 4),
        )
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

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

    def _update_current_tooltip(self, *_args) -> None:
        self.setToolTip(self.itemText(self.currentIndex()) if self.currentIndex() >= 0 else "")
