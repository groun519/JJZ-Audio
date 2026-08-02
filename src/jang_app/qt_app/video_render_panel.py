from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.studio_range_editor import StudioRangeEditor
from jang_app.qt_app.widgets import SvgIconButton, TaskActionWidget


class VideoRenderPanel(QWidget):
    range_changed = Signal(int, int)
    render_requested = Signal()
    open_location_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._result_path: Path | None = None
        self.range_editor = StudioRangeEditor("Video Range")
        self.range_editor.range_changed.connect(self.range_changed.emit)
        self.action = TaskActionWidget("Video Export", "Render")
        self.action.triggered.connect(self.render_requested.emit)
        self.action.set_action_enabled(False)
        self.action.layout().setContentsMargins(14, 12, 14, 12)
        self.action.layout().setSpacing(10)
        self.open_button = SvgIconButton("folder", size=30)
        self.open_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_button, "Open video export location")
        self.open_button.clicked.connect(self._open_result)
        self.open_button.hide()

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.action, 1)
        action_row.addWidget(self.open_button, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self.range_editor, 0)
        layout.addLayout(action_row)
        layout.addStretch(1)

    def set_timeline(self, duration_ms: int, start_ms: int, end_ms: int) -> None:
        self.range_editor.set_timeline(duration_ms, start_ms, end_ms)

    def set_action_enabled(self, enabled: bool) -> None:
        self.action.set_action_enabled(enabled)

    def set_running(self, running: bool) -> None:
        self.action.set_running(running)

    def set_progress(self, value: int) -> None:
        self.action.set_progress(value)

    def set_status(self, status: str, detail: str = "") -> None:
        self.action.set_status(status)
        self.action.status_label.setToolTip(detail)

    def set_result(self, path: Path | None) -> None:
        self._result_path = path
        self.open_button.setVisible(path is not None)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.range_editor.set_theme_mode(theme_mode)
        self.open_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.range_editor.apply_language()
        set_translated_tooltip(self.open_button, "Open video export location")

    def _open_result(self) -> None:
        if self._result_path is not None:
            self.open_location_requested.emit(self._result_path)
