from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from jang_app.qt_app.widgets import FeedbackButton


class SegmentedStack(QWidget):
    current_changed = Signal(int)

    def __init__(self, sections: Iterable[tuple[str, QWidget]]) -> None:
        super().__init__()
        section_items = tuple(sections)
        if not section_items:
            raise ValueError("SegmentedStack requires at least one section")

        control = QFrame()
        control.setObjectName("SegmentedControl")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.stack = QStackedWidget()
        for index, (label, page) in enumerate(section_items):
            button = FeedbackButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.button_group.addButton(button, index)
            control_layout.addWidget(button, 1)
            self.stack.addWidget(page)
        self.button_group.idClicked.connect(self.set_current_index)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(control, 0)
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
