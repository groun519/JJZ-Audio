from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.widgets import SvgIconButton


class StudioRangeEditor(QFrame):
    range_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._theme_mode = "white"

        title = QLabel("Output Range")
        title.setObjectName("SectionTitle")
        self.reset_button = SvgIconButton("refresh", size=30)
        self.reset_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.reset_button, "Reset output range")
        self.reset_button.clicked.connect(self._reset_range)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title, 1)
        header.addWidget(self.reset_button, 0)

        self.slider = TimelineRangeSlider()
        self.slider.range_changed.connect(self._on_range_changed)

        start_caption = QLabel("Start")
        start_caption.setObjectName("StudioRangeCaption")
        self.start_value = QLabel("00:00.000")
        self.start_value.setObjectName("StudioRangeValue")
        end_caption = QLabel("End")
        end_caption.setObjectName("StudioRangeCaption")
        self.end_value = QLabel("00:00.000")
        self.end_value.setObjectName("StudioRangeValue")

        values = QHBoxLayout()
        values.setContentsMargins(0, 0, 0, 0)
        values.setSpacing(8)
        values.addWidget(start_caption, 0)
        values.addWidget(self.start_value, 0)
        values.addStretch(1)
        values.addWidget(end_caption, 0)
        values.addWidget(self.end_value, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self.slider)
        layout.addLayout(values)
        self.set_timeline(0, 0, 0)

    def set_timeline(self, duration_ms: int, start_ms: int, end_ms: int) -> None:
        self.slider.set_range(duration_ms, start_ms, end_ms)
        self._update_values()
        enabled = duration_ms > 0
        self.slider.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)

    def range_values(self) -> tuple[int, int]:
        return self.slider.start_ms, self.slider.end_ms

    def session_values(self) -> tuple[int, int]:
        if self.slider.start_ms == 0 and self.slider.end_ms == self.slider.duration_ms:
            return 0, 0
        return self.range_values()

    def playback_bounds(self) -> tuple[int, int]:
        return self.slider.start_ms, self.slider.end_ms

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.slider.set_theme_mode(theme_mode)
        self.reset_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.reset_button, "Reset output range")

    def _reset_range(self) -> None:
        if self.slider.duration_ms <= 0:
            return
        self.slider.set_values(0, self.slider.duration_ms, emit=True)

    def _on_range_changed(self, start_ms: int, end_ms: int) -> None:
        self._update_values()
        self.range_changed.emit(start_ms, end_ms)

    def _update_values(self) -> None:
        self.start_value.setText(_format_time(self.slider.start_ms))
        self.end_value.setText(_format_time(self.slider.end_ms))


class TimelineRangeSlider(QWidget):
    range_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.duration_ms = 0
        self.start_ms = 0
        self.end_ms = 0
        self._active_handle = ""
        self._pressed = False
        self._theme_mode = "white"
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_range(self, duration_ms: int, start_ms: int, end_ms: int) -> None:
        self.duration_ms = max(0, int(duration_ms))
        resolved_end = self.duration_ms if end_ms <= 0 else end_ms
        self.set_values(start_ms, resolved_end, emit=False)

    def set_values(self, start_ms: int, end_ms: int, *, emit: bool) -> None:
        if self.duration_ms <= 0:
            start, end = 0, 0
        else:
            minimum_span = min(100, self.duration_ms)
            start = max(0, min(int(start_ms), self.duration_ms - minimum_span))
            end = max(start + minimum_span, min(int(end_ms), self.duration_ms))
        changed = (start, end) != (self.start_ms, self.end_ms)
        self.start_ms, self.end_ms = start, end
        self.update()
        if emit and changed:
            self.range_changed.emit(start, end)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = _slider_colors(self._theme_mode, self.isEnabled())
        track = self._track_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(colors["track"])))
        painter.drawRoundedRect(track, 3, 3)

        if self.duration_ms <= 0:
            return
        start_x = self._x_for_value(self.start_ms)
        end_x = self._x_for_value(self.end_ms)
        selection = QRectF(start_x, track.top(), max(1.0, end_x - start_x), track.height())
        painter.setBrush(QBrush(QColor(colors["selection"])))
        painter.drawRoundedRect(selection, 3, 3)

        for handle, x in (("start", start_x), ("end", end_x)):
            active = handle == self._active_handle
            rect = QRectF(x - 5, track.center().y() - 13, 10, 26)
            painter.setBrush(QBrush(QColor(colors["active"] if active else colors["handle"])))
            painter.setPen(QPen(QColor(colors["border"]), 1))
            painter.drawRoundedRect(rect, 4, 4)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors["focus"]), 1))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 9, 9)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.duration_ms <= 0:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        value = self._value_for_x(event.position().x())
        self._active_handle = "start" if abs(value - self.start_ms) <= abs(value - self.end_ms) else "end"
        self._pressed = True
        self._move_active_handle(value)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pressed:
            self._move_active_handle(self._value_for_x(event.position().x()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.duration_ms <= 0 or event.key() not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            super().keyPressEvent(event)
            return
        if not self._active_handle:
            self._active_handle = "start"
        step = 100 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1000
        direction = -1 if event.key() == Qt.Key.Key_Left else 1
        current = self.start_ms if self._active_handle == "start" else self.end_ms
        self._move_active_handle(current + step * direction)

    def _move_active_handle(self, value: int) -> None:
        minimum_span = min(100, self.duration_ms)
        if self._active_handle == "start":
            self.set_values(min(value, self.end_ms - minimum_span), self.end_ms, emit=True)
        else:
            self.set_values(self.start_ms, max(value, self.start_ms + minimum_span), emit=True)

    def _track_rect(self) -> QRectF:
        return QRectF(12, self.height() / 2 - 3, max(1, self.width() - 24), 6)

    def _x_for_value(self, value: int) -> float:
        track = self._track_rect()
        ratio = value / self.duration_ms if self.duration_ms > 0 else 0.0
        return track.left() + track.width() * max(0.0, min(1.0, ratio))

    def _value_for_x(self, x: float) -> int:
        track = self._track_rect()
        ratio = (x - track.left()) / track.width()
        return round(max(0.0, min(1.0, ratio)) * self.duration_ms)


def _format_time(value_ms: int) -> str:
    total_ms = max(0, value_ms)
    minutes, remainder = divmod(total_ms, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _slider_colors(theme_mode: str, enabled: bool) -> dict[str, str]:
    if theme_mode == "dark":
        colors = {
            "track": "#484843",
            "selection": "#ecebe7",
            "handle": "#ecebe7",
            "active": "#ffffff",
            "border": "#151515",
            "focus": "#898780",
        }
    else:
        colors = {
            "track": "#d8d0c2",
            "selection": "#10100e",
            "handle": "#fffdf7",
            "active": "#10100e",
            "border": "#10100e",
            "focus": "#6e6a61",
        }
    if not enabled:
        colors["selection"] = colors["track"]
        colors["handle"] = colors["track"]
        colors["active"] = colors["track"]
    return colors
