from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_text
from jang_app.qt_app.widgets import FeedbackButton


class LibraryWorkspace(QWidget):
    current_changed = Signal(int)

    def __init__(self, sections: Iterable[tuple[str, QWidget]]) -> None:
        super().__init__()
        section_items = tuple(sections)
        if not section_items:
            raise ValueError("LibraryWorkspace requires at least one section")

        header = QFrame()
        header.setObjectName("LibraryWorkspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(6)

        title = QLabel()
        title.setObjectName("LibraryWorkspaceTitle")
        set_translated_text(title, "Library")
        header_layout.addWidget(title, 0)
        header_layout.addSpacing(24)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.stack = QStackedWidget()
        self.section_buttons: list[FeedbackButton] = []
        self._section_labels: list[str] = []
        self._section_counts: list[int | None] = []
        for index, (label, page) in enumerate(section_items):
            button = FeedbackButton()
            button.setObjectName("LibrarySectionTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            set_translated_text(button, label)
            self.button_group.addButton(button, index)
            self.section_buttons.append(button)
            self._section_labels.append(label)
            self._section_counts.append(None)
            header_layout.addWidget(button, 0)
            self.stack.addWidget(page)
        header_layout.addStretch(1)
        self.button_group.idClicked.connect(self.set_current_index)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(header, 0)
        layout.addWidget(self.stack, 1)

    def current_index(self) -> int:
        return self.stack.currentIndex()

    def set_current_index(self, index: int) -> None:
        if not 0 <= index < self.stack.count():
            return
        changed = index != self.stack.currentIndex()
        self.stack.setCurrentIndex(index)
        button = self.button_group.button(index)
        if button is not None:
            button.setChecked(True)
        if changed:
            self.current_changed.emit(index)

    def set_section_count(self, index: int, count: int) -> None:
        if not 0 <= index < len(self.section_buttons):
            return
        normalized_count = max(0, count)
        self._section_counts[index] = normalized_count
        set_translated_text(
            self.section_buttons[index],
            f"{self._section_labels[index]} {{count}}",
            count=normalized_count,
        )
