from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_text
from jang_app.qt_app.widgets import FeedbackButton


class ExportActionFooter(QWidget):
    triggered = Signal()

    def __init__(self, action_text: str = "Export") -> None:
        super().__init__()
        self._action_enabled = True
        self._running = False

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ExportInlineProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()

        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ProgressValue")
        self.percent_label.hide()

        self.status_label = QLabel()
        self.status_label.setObjectName("AudioExportStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        self.button = FeedbackButton()
        self.button.setObjectName("PrimaryButton")
        self.button.setMinimumWidth(120)
        set_translated_text(self.button, action_text)
        self.button.clicked.connect(self.triggered.emit)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.percent_label, 0)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)
        action_row.addWidget(self.status_label, 1)
        action_row.addWidget(self.button, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(progress_row)
        layout.addLayout(action_row)

    def set_action_enabled(self, is_enabled: bool) -> None:
        self._action_enabled = is_enabled
        self._sync_enabled()

    def set_running(self, is_running: bool) -> None:
        self._running = is_running
        self._sync_enabled()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.percent_label.setText(f"{progress}%")
        is_visible = self._running or 0 < progress < 100
        self.progress_bar.setVisible(is_visible)
        self.percent_label.setVisible(is_visible)

    def set_status(self, text: str) -> None:
        value = text.strip()
        set_translated_text(self.status_label, value)
        self.status_label.setVisible(bool(value))

    def _sync_enabled(self) -> None:
        self.button.setEnabled(self._action_enabled and not self._running)
