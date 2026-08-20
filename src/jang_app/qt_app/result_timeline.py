from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.widgets import WaveformView
from jang_app.services.audio_metadata import format_duration
from jang_app.services.i18n import tr


RESULT_TRACK_HEADER_WIDTH = 208


class ResultTimelineWaveform(WaveformView):
    """Result-only waveform with a compact DAW-style surface."""

    def __init__(self) -> None:
        super().__init__()
        self._duration_ms = 0

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = theme_tokens(self._theme_mode)
        outer = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        radius = 8.0
        surface = (
            QColor("#191919")
            if self._theme_mode == "dark"
            else QColor(tokens["surface"])
        )
        painter.setPen(QPen(QColor(tokens["border"]), 1))
        painter.setBrush(surface)
        painter.drawRoundedRect(outer, radius, radius)

        content = outer.adjusted(12, 10, -12, -10)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(outer, radius, radius)
        painter.setClipPath(clip)
        grid = QColor("#292927") if self._theme_mode == "dark" else QColor("#ebe6dc")
        painter.setPen(QPen(grid, 1))
        grid_positions = timeline_ticks(
            self._duration_ms,
            available_width=content.width(),
        )
        for position_ms in grid_positions[1:]:
            if position_ms >= self._duration_ms:
                continue
            x = content.left() + content.width() * position_ms / self._duration_ms
            painter.drawLine(QPointF(x, outer.top()), QPointF(x, outer.bottom()))

        midline = (
            QColor("#55544f")
            if self._theme_mode == "dark"
            else QColor("#c2baad")
        )
        painter.setPen(QPen(midline, 1))
        painter.drawLine(
            QPointF(content.left(), content.center().y()),
            QPointF(content.right(), content.center().y()),
        )

        if not self._peaks:
            painter.setPen(QPen(QColor(tokens["muted"]), 1))
            placeholder = self._error or (
                tr("Loading waveform...")
                if self._is_loading
                else tr("No waveform loaded")
            )
            painter.drawText(content, Qt.AlignmentFlag.AlignCenter, placeholder)
        else:
            wave = QColor(tokens["faint"] if self._muted else tokens["text"])
            painter.setPen(QPen(wave, 1))
            step_width = content.width() / max(1, len(self._peaks) - 1)
            max_height = content.height() * 0.45
            center_y = content.center().y()
            for index, peak in enumerate(self._peaks):
                x = content.left() + index * step_width
                height = max(1.0, peak * max_height)
                painter.drawLine(
                    QPointF(x, center_y - height),
                    QPointF(x, center_y + height),
                )

        head_x = content.left() + content.width() * self._playhead_ratio
        painter.setPen(QPen(QColor(tokens["pair_accent"]), 2))
        painter.drawLine(QPointF(head_x, outer.top()), QPointF(head_x, outer.bottom()))
        painter.restore()

    def _seek_to_position(self, x_position: float) -> None:
        content = QRectF(self.rect()).adjusted(20, 18, -20, -18)
        if content.width() <= 0 or not self._path:
            return
        ratio = max(0.0, min(1.0, (x_position - content.left()) / content.width()))
        self.set_playhead_ratio(ratio)
        self.seek_requested.emit(ratio)


class ResultTimelineRuler(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ResultTimelineRuler")
        self.setFixedHeight(28)
        self._duration_ms = 0
        self._playhead_ratio = 0.0
        self._theme = theme_tokens("white")

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.update()

    def set_playhead_ratio(self, ratio: float) -> None:
        self._playhead_ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme = theme_tokens(theme_mode)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor(self._theme["faint"]))
        painter.drawText(
            QRectF(13, 0, RESULT_TRACK_HEADER_WIDTH - 26, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            tr("Track"),
        )
        axis_left = RESULT_TRACK_HEADER_WIDTH + 20
        axis_right = max(axis_left + 1, self.width() - 20)
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(axis_left, self.height() - 1, axis_right, self.height() - 1)
        if self._duration_ms > 0:
            painter.setPen(QColor(self._theme["muted"]))
            for position_ms in timeline_ticks(
                self._duration_ms,
                available_width=axis_right - axis_left,
            ):
                ratio = min(1.0, position_ms / self._duration_ms)
                x = axis_left + (axis_right - axis_left) * ratio
                painter.drawLine(int(x), self.height() - 5, int(x), self.height())
                painter.drawText(
                    QRectF(x - 22, 0, 44, self.height() - 5),
                    Qt.AlignmentFlag.AlignCenter,
                    format_duration(position_ms),
                )

        head_x = axis_left + (axis_right - axis_left) * self._playhead_ratio
        marker = QPainterPath()
        marker.moveTo(head_x - 4, self.height() - 5)
        marker.lineTo(head_x + 4, self.height() - 5)
        marker.lineTo(head_x, self.height() - 1)
        marker.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme["pair_accent"]))
        painter.drawPath(marker)


def timeline_ticks(
    duration_ms: int,
    *,
    available_width: float | None = None,
) -> tuple[int, ...]:
    if duration_ms <= 0:
        return ()
    interval = _tick_interval(duration_ms)
    if available_width is not None:
        while available_width * interval / duration_ms < 58:
            interval *= 2
    positions = list(range(0, duration_ms, interval))
    show_duration = available_width is None or not positions or (
        available_width * (duration_ms - positions[-1]) / duration_ms >= 50
    )
    if show_duration and (not positions or positions[-1] != duration_ms):
        positions.append(duration_ms)
    return tuple(positions)


def result_timeline_stylesheet(tokens: dict[str, str]) -> str:
    return f"""
        QFrame#ResultTimelineSurface {{
            background: transparent;
            border: none;
        }}
        QFrame#ResultTimelineTrack {{
            background: {tokens['card']};
            border: 1px solid {tokens['border']};
            border-radius: 11px;
        }}
        QFrame#ResultTimelineTrackHeader {{
            background: {tokens['raised']};
            border: none;
            border-right: 1px solid {tokens['border']};
            border-top-left-radius: 10px;
            border-bottom-left-radius: 10px;
        }}
        QLabel#ResultTimelineTrackTitle {{
            color: {tokens['text']};
            font-weight: 800;
        }}
        QLabel#ResultTimelineTrackDetail {{
            color: {tokens['muted']};
            font-size: 10px;
        }}
        QFrame#ResultTimelineMixControl {{
            background: transparent;
            border: none;
        }}
    """


def _tick_interval(duration_ms: int) -> int:
    if duration_ms <= 60_000:
        return 10_000
    if duration_ms <= 240_000:
        return 30_000
    if duration_ms <= 600_000:
        return 60_000
    return 120_000
