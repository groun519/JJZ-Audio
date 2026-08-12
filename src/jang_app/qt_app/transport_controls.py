from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.widgets import ScrollSafeSlider, SvgIconButton
from jang_app.services.audio_metadata import format_duration
from jang_app.services.i18n import tr


TRANSPORT_BUTTON_SIZE = 34


class TransportControls(QWidget):
    play_toggled = Signal()
    seek_requested = Signal(int)

    def __init__(self, header_widget: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("TransportControls")
        self._duration_ms = 0
        self._is_syncing = False
        self._shortcut_hint = ""
        self._is_playing = False

        self.play_button = SvgIconButton("play", size=TRANSPORT_BUTTON_SIZE)
        self.play_button.setObjectName("TransportPlayButton")
        set_translated_tooltip(self.play_button, "Play")
        self.play_button.clicked.connect(self.play_toggled.emit)

        self.slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("TransportSlider")
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.slider.sliderMoved.connect(self._emit_seek_requested)

        self.time_label = QLabel("00:00 / --:--")
        self.time_label.setObjectName("TransportTime")
        self.time_label.setMinimumWidth(104)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        timeline_row = 1 if header_widget is not None else 0
        if header_widget is not None:
            layout.addWidget(header_widget, 0, 1, 1, 2)
        layout.addWidget(self.play_button, timeline_row, 0)
        layout.addWidget(self.slider, timeline_row, 1)
        layout.addWidget(self.time_label, timeline_row, 2)
        layout.setColumnStretch(1, 1)
        self.clear()

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        enabled = self._duration_ms > 0
        self.slider.setEnabled(enabled)
        self.play_button.setEnabled(enabled)

    def clear(self) -> None:
        self.set_duration(0)
        self.set_playing(False)
        self.set_position(0)

    def set_playing(self, is_playing: bool) -> None:
        self._is_playing = is_playing
        self.play_button.set_icon_name("stop" if is_playing else "play")
        self._refresh_play_tooltip()

    def set_shortcut_hint(self, shortcut: str) -> None:
        self._shortcut_hint = shortcut.strip()
        self._refresh_play_tooltip()

    def set_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        if duration_ms is not None:
            self.set_duration(duration_ms)
        duration = self._duration_ms
        position = max(0, min(position_ms, duration)) if duration > 0 else 0
        slider_value = int(position / duration * 1000) if duration > 0 else 0
        self._is_syncing = True
        self.slider.setValue(max(0, min(1000, slider_value)))
        self._is_syncing = False
        self.time_label.setText(f"{format_duration(position)} / {format_duration(duration)}")

    def set_theme_mode(self, theme_mode: str) -> None:
        self.play_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._refresh_play_tooltip()

    def _refresh_play_tooltip(self) -> None:
        label = tr("Stop" if self._is_playing else "Play")
        self.play_button.setToolTip(
            f"{label} ({self._shortcut_hint})" if self._shortcut_hint else label
        )

    def _emit_seek_requested(self, value: int) -> None:
        if self._is_syncing or self._duration_ms <= 0:
            return
        position_ms = int(self._duration_ms * max(0, min(1000, value)) / 1000)
        self.seek_requested.emit(position_ms)
