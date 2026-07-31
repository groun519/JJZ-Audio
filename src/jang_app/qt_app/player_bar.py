from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout

from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.audio_metadata import format_duration


class GlobalPlayerBar(QFrame):
    play_toggled = Signal()
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("GlobalPlayerBar")
        self.setFixedHeight(82)
        self._duration_ms = 0
        self._is_syncing = False

        self.play_button = SvgIconButton("play", size=38)
        self.play_button.setToolTip("Play")
        self.play_button.clicked.connect(self.play_toggled.emit)

        self.context_label = QLabel("")
        self.context_label.setObjectName("PlayerContext")
        self.context_label.setFixedWidth(72)
        self.context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("No sound selected")
        self.title_label.setObjectName("PlayerTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.time_label = QLabel("00:00 / --:--")
        self.time_label.setObjectName("PlayerTime")
        self.time_label.setMinimumWidth(96)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("PlayerSlider")
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self._emit_seek_requested)

        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(12)
        info_row.addWidget(self.context_label, 0)
        info_row.addWidget(self.title_label, 1)
        info_row.addWidget(self.time_label, 0)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addLayout(info_row)
        content_layout.addWidget(self.slider)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)
        layout.addWidget(self.play_button, 0)
        layout.addLayout(content_layout, 1)

        self.clear()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.play_button.set_theme_mode(theme_mode)

    def set_queue(self, context: str, title: str, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        self.context_label.setText(context)
        self.context_label.setVisible(bool(context))
        self.title_label.setText(title.strip() or "Untitled")
        self.slider.setEnabled(self._duration_ms > 0)
        self.play_button.setEnabled(self._duration_ms > 0)

    def clear(self) -> None:
        self._duration_ms = 0
        self.context_label.setText("")
        self.context_label.hide()
        self.title_label.setText("No sound selected")
        self.slider.setEnabled(False)
        self.play_button.setEnabled(False)
        self.set_playing(False)
        self.set_position(0)

    def set_playing(self, is_playing: bool) -> None:
        self.play_button.set_icon_name("pause" if is_playing else "play")
        self.play_button.setToolTip("Pause" if is_playing else "Play")

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        if duration_ms is not None:
            self._duration_ms = max(0, duration_ms)
            self.slider.setEnabled(self._duration_ms > 0)
            self.play_button.setEnabled(self._duration_ms > 0)
        duration = self._duration_ms
        position = max(0, min(position_ms, duration)) if duration > 0 else 0
        slider_value = int(position / duration * 1000) if duration > 0 else 0
        self._is_syncing = True
        self.slider.setValue(max(0, min(1000, slider_value)))
        self._is_syncing = False
        self.time_label.setText(f"{format_duration(position)} / {format_duration(duration)}")

    def _emit_seek_requested(self, value: int) -> None:
        if self._is_syncing or self._duration_ms <= 0:
            return
        position_ms = int(self._duration_ms * max(0, min(1000, value)) / 1000)
        self.seek_requested.emit(position_ms)
