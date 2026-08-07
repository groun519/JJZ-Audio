from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton


SOURCE_FILTERS = ("local", "youtube", "output")


class LibrarySourceFilter(QFrame):
    selection_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LibrarySourceFilter")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.buttons: dict[str, FeedbackButton] = {}
        for source_type, label in (
            ("all", "All Sources"),
            ("local", "LOCAL"),
            ("youtube", "YOUTUBE"),
            ("output", "OUTPUT"),
        ):
            button = FeedbackButton()
            button.setObjectName("LibrarySourceFlag")
            button.setProperty("sourceType", source_type)
            button.setCheckable(True)
            set_translated_text(button, label)
            button.clicked.connect(
                lambda checked, value=source_type: self._on_flag_clicked(value, checked)
            )
            self.buttons[source_type] = button
            layout.addWidget(button)

        self.buttons["all"].setChecked(True)

    def selected_sources(self) -> frozenset[str]:
        return frozenset(
            source_type
            for source_type in SOURCE_FILTERS
            if self.buttons[source_type].isChecked()
        )

    def apply_language(self) -> None:
        apply_widget_language(self)

    def _on_flag_clicked(self, source_type: str, is_checked: bool) -> None:
        if source_type == "all":
            self._select_all()
        else:
            self.buttons["all"].setChecked(False)
            if not is_checked and not self.selected_sources():
                self.buttons["all"].setChecked(True)
        self.selection_changed.emit()

    def _select_all(self) -> None:
        self.buttons["all"].setChecked(True)
        for source_type in SOURCE_FILTERS:
            self.buttons[source_type].setChecked(False)
