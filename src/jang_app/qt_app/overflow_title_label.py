from __future__ import annotations

from PySide6.QtCore import Property, QPropertyAnimation, QEasingCurve, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class OverflowTextLabel(QWidget):
    """Single-line text with a fade edge and hover-to-reveal marquee."""

    def __init__(self, text: str = "", *, object_name: str = "", fixed_height: int = 22) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(fixed_height)
        self.setToolTip(text)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._text = text
        self._scroll_offset = 0.0
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(320)
        self._hover_timer.timeout.connect(self._start_marquee)
        self._animation = QPropertyAnimation(self, b"scrollOffset", self)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.setToolTip(text)
        self._reset_marquee()
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._maximum_offset() > 0:
            self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_timer.stop()
        self._animate_to(0.0, 180)
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._reset_marquee()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self._text)
        available_width = max(0, self.width())
        if text_width <= available_width:
            painter.setPen(self.palette().windowText().color())
        else:
            painter.setPen(QPen(QBrush(self._text_gradient()), 1))
        baseline = (self.height() - metrics.height()) / 2 + metrics.ascent()
        painter.drawText(-self._scroll_offset, baseline, self._text)

    def get_scroll_offset(self) -> float:
        return self._scroll_offset

    def set_scroll_offset(self, value: float) -> None:
        self._scroll_offset = max(0.0, min(value, self._maximum_offset()))
        self.update()

    scrollOffset = Property(float, get_scroll_offset, set_scroll_offset)

    def _maximum_offset(self) -> float:
        return max(0.0, float(self.fontMetrics().horizontalAdvance(self._text) - self.width()))

    def _start_marquee(self) -> None:
        maximum = self._maximum_offset()
        if maximum <= 0:
            return
        duration = max(600, int(maximum / 42.0 * 1000))
        self._animate_to(maximum, duration)

    def _animate_to(self, value: float, duration: int) -> None:
        self._animation.stop()
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._scroll_offset)
        self._animation.setEndValue(value)
        self._animation.start()

    def _reset_marquee(self) -> None:
        self._hover_timer.stop()
        self._animation.stop()
        self._scroll_offset = 0.0

    def _text_gradient(self) -> QLinearGradient:
        color = self.palette().windowText().color()
        transparent = QColor(color)
        transparent.setAlpha(0)
        width = max(1, self.width())
        edge = min(0.12, 20.0 / width)
        gradient = QLinearGradient(0, 0, width, 0)
        if self._scroll_offset > 0.5:
            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(edge, color)
        else:
            gradient.setColorAt(0.0, color)
        if self._scroll_offset < self._maximum_offset() - 0.5:
            gradient.setColorAt(1.0 - edge, color)
            gradient.setColorAt(1.0, transparent)
        else:
            gradient.setColorAt(1.0, color)
        return gradient


class OverflowTitleLabel(OverflowTextLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text, object_name="LibraryRowTitle", fixed_height=22)
