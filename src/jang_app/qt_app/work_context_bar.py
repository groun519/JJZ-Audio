from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.services.work_context import WorkContextDisplay


class WorkContextBar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WorkContextBar")
        self.setFixedHeight(46)
        self._display = WorkContextDisplay(is_active=False)

        self.work_badge = QLabel("WORK")
        self.work_badge.setObjectName("WorkBadge")
        self.work_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.work_badge.setFixedWidth(54)

        self.source_badge = QLabel("")
        self.source_badge.setObjectName("WorkSourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(48)

        self.title_label = QLabel("")
        self.title_label.setObjectName("WorkTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.output_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        layout.addWidget(self.work_badge, 0)
        layout.addWidget(self.source_badge, 0)
        layout.addLayout(title_column, 2)
        layout.addWidget(self.detail_label, 1)
        layout.addWidget(self.state_label, 0)
        self.set_display(WorkContextDisplay(is_active=False))

    def set_display(self, display: WorkContextDisplay) -> None:
        self._display = display
        self.setVisible(display.is_active)
        if not display.is_active:
            return

        set_translated_text(self.source_badge, display.source_label)
        self.source_badge.setProperty("sourceType", display.source_type)
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        self.title_label.setText(display.title)
        self.detail_label.setText(display.detail_label)
        set_translated_text(self.state_label, display.state_label)

        output_text = display.output_label.strip()
        self.output_label.setText(output_text)
        self.output_label.setVisible(bool(output_text))

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.set_display(self._display)
