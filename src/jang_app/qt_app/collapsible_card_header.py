from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import SvgIconButton


class CollapsibleCardHeader(QWidget):
    toggled = Signal(bool)

    def __init__(self, title_key: str, *, expanded: bool = False) -> None:
        super().__init__()
        self._expanded = expanded

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionSubtitle")
        set_translated_text(self.title_label, title_key)

        self.status_host = QWidget()
        self.status_layout = QHBoxLayout(self.status_host)
        self.status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_layout.setSpacing(6)
        self.status_host.hide()

        self.summary_label = QLabel()
        self.summary_label.setObjectName("CollapsibleHeaderSummary")
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setMaximumWidth(118)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.toggle_button = SvgIconButton("chevron_down", size=28)
        self.toggle_button.setObjectName("CollapsibleHeaderButton")
        self.toggle_button.setCheckable(True)
        self.toggle_button.clicked.connect(self._on_toggled)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_host)
        layout.addStretch(1)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.toggle_button)

        self.set_expanded(expanded)

    def add_status_widget(self, widget: QWidget) -> None:
        self.status_layout.addWidget(widget)
        self.status_host.show()

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)
        self.summary_label.setVisible(bool(text.strip()))

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.toggle_button.setChecked(self._expanded)
        self.toggle_button.set_icon_name(
            "chevron_up" if self._expanded else "chevron_down"
        )
        self.apply_language()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_theme_mode(self, theme_mode: str) -> None:
        self.toggle_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_tooltip(
            self.toggle_button,
            "Collapse detailed settings"
            if self._expanded
            else "Expand detailed settings",
        )

    def _on_toggled(self, expanded: bool) -> None:
        self.set_expanded(expanded)
        self.toggled.emit(self._expanded)
