from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter, QFrame, QHBoxLayout, QLabel, QSizePolicy

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import ScrollSafeComboBox
from jang_app.services.i18n import tr
from jang_app.services.work_context import WorkContextDisplay


class WorkContextBar(QFrame):
    song_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkContextBar")
        self.setFixedHeight(52)
        self._display = WorkContextDisplay(is_active=False)
        self._loading = False
        self._selected_song_id = ""

        self.work_badge = QLabel("WORK")
        self.work_badge.setObjectName("WorkBadge")
        self.work_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.work_badge.setFixedWidth(54)

        self.source_badge = QLabel("")
        self.source_badge.setObjectName("WorkSourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(48)

        self.song_combo = ScrollSafeComboBox()
        self.song_combo.setObjectName("WorkSongCombo")
        self.song_combo.setEditable(True)
        self.song_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.song_combo.setMinimumWidth(260)
        self.song_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.song_combo.lineEdit().setClearButtonEnabled(True)
        self.song_combo.activated.connect(self._activate_index)
        self.song_combo.lineEdit().returnPressed.connect(self._activate_search_text)
        completer = self.song_combo.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("WorkDetail")
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.output_label = QLabel("")
        self.output_label.setObjectName("WorkOutput")
        self.output_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.output_label.hide()

        self.state_label = QLabel("")
        self.state_label.setObjectName("WorkStateBadge")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setMinimumWidth(86)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(10)
        layout.addWidget(self.work_badge, 0)
        layout.addWidget(self.source_badge, 0)
        layout.addWidget(self.song_combo, 2)
        layout.addWidget(self.detail_label, 1)
        layout.addWidget(self.output_label, 1)
        layout.addWidget(self.state_label, 0)
        self.set_songs(())
        self.set_display(WorkContextDisplay(is_active=False))

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self._loading = True
        self.song_combo.blockSignals(True)
        self.song_combo.clear()
        self.song_combo.addItem(tr("Select work song"), "")
        for song_id, title in songs:
            self.song_combo.addItem(title, song_id)
        self.song_combo.blockSignals(False)
        self._loading = False
        self.select_song(selected_id)

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        index = self.song_combo.findData(song_id)
        selected_index = index if index >= 0 else 0
        selected_id = str(self.song_combo.itemData(selected_index) or "")
        changed = selected_id != self._selected_song_id
        self._selected_song_id = selected_id
        self.song_combo.setCurrentIndex(selected_index)
        if emit and changed:
            self.song_changed.emit(selected_id)

    def selected_song_id(self) -> str:
        return self._selected_song_id

    def has_song(self, song_id: str) -> bool:
        return self.song_combo.findData(song_id) >= 0

    def set_display(self, display: WorkContextDisplay) -> None:
        self._display = display
        self.setVisible(True)
        self.source_badge.setVisible(display.is_active)
        self.detail_label.setVisible(display.is_active and bool(display.detail_label))
        self.state_label.setVisible(display.is_active and bool(display.state_label))
        if not display.is_active:
            self.output_label.hide()
            return

        set_translated_text(self.source_badge, display.source_label)
        self.source_badge.setProperty("sourceType", display.source_type)
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        self.detail_label.setText(display.detail_label)
        set_translated_text(self.state_label, display.state_label)

        output_text = display.output_label.strip()
        self.output_label.setText(output_text)
        self.output_label.setVisible(bool(output_text))

    def apply_language(self) -> None:
        apply_widget_language(self)
        if self.song_combo.count() > 0:
            self.song_combo.setItemText(0, tr("Select work song"))
        self.song_combo.lineEdit().setPlaceholderText(tr("Search work songs"))
        self.set_display(self._display)

    def _activate_index(self, index: int) -> None:
        if self._loading or index < 0:
            return
        selected_id = str(self.song_combo.itemData(index) or "")
        self._selected_song_id = selected_id
        self.song_changed.emit(selected_id)

    def _activate_search_text(self) -> None:
        query = self.song_combo.currentText().strip().casefold()
        if not query:
            self.select_song("", emit=True)
            return
        for index in range(1, self.song_combo.count()):
            if self.song_combo.itemText(index).strip().casefold() == query:
                song_id = str(self.song_combo.itemData(index) or "")
                self.select_song(song_id, emit=True)
                return
        self.select_song(self._selected_song_id)
