from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from jang_app.qt_app.theme import theme_tokens
from jang_app.services.i18n import tr
from jang_app.services.model_precision_benchmark import (
    REFERENCE_CENTER_MIDI,
    STABLE_SCORE_THRESHOLD,
    USABLE_SCORE_THRESHOLD,
    ModelPrecisionBenchmark,
    ModelPrecisionBenchmarkPoint,
)
from jang_app.services.pitch_profile import midi_note_name


def benchmark_note_label(shift: int | None) -> str:
    if shift is None:
        return "-"
    return midi_note_name(REFERENCE_CENTER_MIDI + shift)


def benchmark_note_range_label(
    low_shift: int | None,
    high_shift: int | None,
) -> str:
    if low_shift is None or high_shift is None:
        return "-"
    low = benchmark_note_label(low_shift)
    high = benchmark_note_label(high_shift)
    return low if low == high else f"{low} ~ {high}"


def benchmark_shift_range_label(
    low_shift: int | None,
    high_shift: int | None,
) -> str:
    if low_shift is None or high_shift is None:
        return "-"
    if low_shift == high_shift:
        return f"{low_shift:+d}"
    return f"{low_shift:+d} ~ {high_shift:+d}"


class BenchmarkNoteRangeView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("BenchmarkNoteRangeView")
        self.setMinimumHeight(78)
        self._report: ModelPrecisionBenchmark | None = None
        self._theme_mode = "white"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(700, 78)

    def set_report(self, report: ModelPrecisionBenchmark | None) -> None:
        self._report = report
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        report = self._report
        if report is None or not report.points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = theme_tokens(self._theme_mode)
        axis = self.rect().adjusted(14, 21, -14, -29)
        low_shift = report.points[0].shift_semitones
        high_shift = report.points[-1].shift_semitones
        if axis.width() <= 0 or high_shift <= low_shift:
            return

        track = QRectF(axis.left(), axis.top(), axis.width(), 8.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens["border"]))
        painter.drawRoundedRect(track, 4.0, 4.0)
        self._draw_range(
            painter,
            track,
            report.usable_low_shift,
            report.usable_high_shift,
            low_shift,
            high_shift,
            _status_color("caution", self._theme_mode),
            opacity=0.56,
        )
        self._draw_range(
            painter,
            track,
            report.recommended_low_shift,
            report.recommended_high_shift,
            low_shift,
            high_shift,
            _status_color("stable", self._theme_mode),
        )

        if report.best_shift_semitones is not None:
            center_x = _shift_x(
                report.best_shift_semitones,
                track,
                low_shift,
                high_shift,
            )
            accent = QColor(tokens["accent"])
            painter.setPen(QPen(accent, 2.0))
            painter.drawLine(
                int(center_x),
                int(track.top() - 8),
                int(center_x),
                int(track.bottom() + 8),
            )
            painter.setPen(accent)
            _set_font_size(painter, 8, bold=True)
            painter.drawText(
                QRectF(center_x - 28, 0, 56, 15),
                Qt.AlignmentFlag.AlignCenter,
                benchmark_note_label(report.best_shift_semitones),
            )

        for shift in _octave_ticks(low_shift, high_shift):
            x = _shift_x(shift, track, low_shift, high_shift)
            alignment = Qt.AlignmentFlag.AlignHCenter
            label_rect = QRectF(x - 27, track.bottom() + 5, 54, 14)
            if shift == low_shift:
                label_rect.moveLeft(track.left())
                alignment = Qt.AlignmentFlag.AlignLeft
            elif shift == high_shift:
                label_rect.moveRight(track.right())
                alignment = Qt.AlignmentFlag.AlignRight
            painter.setPen(QColor(tokens["text"]))
            _set_font_size(painter, 8, bold=True)
            painter.drawText(label_rect, alignment, benchmark_note_label(shift))
            painter.setPen(QColor(tokens["faint"]))
            _set_font_size(painter, 7)
            offset = tr("Reference") if shift == 0 else f"{shift:+d}"
            offset_rect = QRectF(label_rect.left(), label_rect.bottom() - 1, label_rect.width(), 12)
            painter.drawText(offset_rect, alignment, offset)

    @staticmethod
    def _draw_range(
        painter: QPainter,
        track: QRectF,
        low: int | None,
        high: int | None,
        axis_low: int,
        axis_high: int,
        color: QColor,
        *,
        opacity: float = 1.0,
    ) -> None:
        if low is None or high is None:
            return
        left = _shift_x(low, track, axis_low, axis_high)
        right = _shift_x(high, track, axis_low, axis_high)
        fill = QColor(color)
        fill.setAlphaF(opacity)
        painter.setBrush(fill)
        painter.drawRoundedRect(
            QRectF(left, track.top(), max(5.0, right - left), track.height()),
            4.0,
            4.0,
        )


class PrecisionBenchmarkNoteChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PitchHistogram")
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._points: tuple[ModelPrecisionBenchmarkPoint, ...] = ()
        self._center_shift: int | None = None
        self._theme_mode = "white"

    def set_report(self, report: ModelPrecisionBenchmark | None) -> None:
        self._points = report.points if report is not None else ()
        self._center_shift = report.best_shift_semitones if report is not None else None
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        chart = self._chart_rect()
        if chart.width() <= 0 or chart.height() <= 0:
            return
        if not self._points:
            painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                tr("No precise evaluation data"),
            )
            return

        tokens = theme_tokens(self._theme_mode)
        for score, color in (
            (100, QColor(tokens["border"])),
            (STABLE_SCORE_THRESHOLD, _status_color("stable", self._theme_mode)),
            (USABLE_SCORE_THRESHOLD, _status_color("caution", self._theme_mode)),
            (0, QColor(tokens["border"])),
        ):
            y = _score_y(score, chart)
            line_color = QColor(color)
            threshold = score in (STABLE_SCORE_THRESHOLD, USABLE_SCORE_THRESHOLD)
            line_color.setAlphaF(0.42 if threshold else 0.7)
            painter.setPen(QPen(line_color, 1.0))
            painter.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))
            painter.setPen(QColor(tokens["faint"]))
            _set_font_size(painter, 7)
            painter.drawText(
                QRectF(0, y - 7, chart.left() - 7, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(score),
            )

        gap, bar_width = self._bar_geometry(chart)
        for index, point in enumerate(self._points):
            left = chart.left() + index * (bar_width + gap)
            top = _score_y(point.score, chart)
            rect = QRectF(left, top, bar_width, chart.bottom() - top)
            painter.setBrush(_status_color(point.status, self._theme_mode))
            if point.shift_semitones == self._center_shift:
                painter.setPen(QPen(QColor(tokens["accent"]), 1.2))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 2.5, 2.5)

            if point.shift_semitones % 6 == 0:
                painter.setPen(
                    QColor(tokens["accent"])
                    if point.shift_semitones == self._center_shift
                    else QColor(tokens["muted"])
                )
                _set_font_size(
                    painter,
                    7,
                    bold=point.shift_semitones == self._center_shift,
                )
                painter.drawText(
                    QRectF(left - 12, chart.bottom() + 5, bar_width + 24, 16),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    benchmark_note_label(point.shift_semitones),
                )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        point = self._point_at(event.position().x(), event.position().y())
        if point is None:
            QToolTip.hideText()
            return
        offset = f"{point.shift_semitones:+d}"
        message = tr(
            "{note}  /  {shift} pitch  /  stability {score}  /  references {success}/{total}",
            note=benchmark_note_label(point.shift_semitones),
            shift=offset,
            score=point.score,
            success=point.successful_references,
            total=point.total_references,
        )
        QToolTip.showText(event.globalPosition().toPoint(), message, self)

    def leaveEvent(self, _event) -> None:  # noqa: N802
        QToolTip.hideText()

    def _point_at(self, x: float, y: float) -> ModelPrecisionBenchmarkPoint | None:
        chart = self._chart_rect()
        if not chart.contains(x, y) or not self._points:
            return None
        gap, bar_width = self._bar_geometry(chart)
        index = int((x - chart.left()) / (bar_width + gap))
        if not 0 <= index < len(self._points):
            return None
        left = chart.left() + index * (bar_width + gap)
        if x > left + bar_width:
            return None
        return self._points[index]

    def _chart_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(34, 14, -10, -27)

    def _bar_geometry(self, chart: QRectF) -> tuple[float, float]:
        gap = 3.0
        total_gap = gap * max(0, len(self._points) - 1)
        width = max(4.0, (chart.width() - total_gap) / max(1, len(self._points)))
        return gap, width


def _octave_ticks(low_shift: int, high_shift: int) -> tuple[int, ...]:
    return tuple(
        shift
        for shift in range(low_shift, high_shift + 1)
        if shift % 12 == 0
    )


def _shift_x(shift: int, rect: QRectF, low_shift: int, high_shift: int) -> float:
    ratio = (shift - low_shift) / max(1, high_shift - low_shift)
    return rect.left() + rect.width() * ratio


def _score_y(score: int, rect: QRectF) -> float:
    return rect.bottom() - rect.height() * max(0, min(100, score)) / 100.0


def _set_font_size(painter: QPainter, size: int, *, bold: bool = False) -> None:
    font = QFont(painter.font())
    font.setPixelSize(size)
    font.setBold(bold)
    painter.setFont(font)


def _status_color(status: str, theme_mode: str) -> QColor:
    if status == "stable":
        return QColor("#48b48d" if theme_mode == "dark" else "#2c8d6d")
    if status == "caution":
        return QColor("#c99a4f" if theme_mode == "dark" else "#b5781c")
    return QColor("#53575e" if theme_mode == "dark" else "#8e939b")
