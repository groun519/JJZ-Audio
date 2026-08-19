from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from jang_app.qt_app.theme import theme_tokens
from jang_app.services.audio_metadata import format_duration
from jang_app.services.vocal_split import VocalReferenceRegion


class TimelineRangeLane(QWidget):
    """Compact timeline lane for selecting and removing reference ranges."""

    region_activated = Signal(str)
    region_remove_requested = Signal(str)
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TimelineRangeLane")
        self.setMouseTracking(True)
        self.setMinimumHeight(42)
        self._duration_ms = 0
        self._regions: tuple[VocalReferenceRegion, ...] = ()
        self._selected_region_id = ""
        self._hovered_region_id = ""
        self._theme_mode = "white"

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.update()

    def set_regions(
        self,
        regions: tuple[VocalReferenceRegion, ...],
        selected_region_id: str = "",
    ) -> None:
        self._regions = tuple(regions)
        available = {region.region_id for region in self._regions}
        self._selected_region_id = (
            selected_region_id if selected_region_id in available else ""
        )
        self.update()

    def selected_region_id(self) -> str:
        return self._selected_region_id

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = theme_tokens(self._theme_mode)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(tokens["raised"]))
        content = self._content_rect()
        painter.setPen(QPen(QColor(tokens["border"]), 1))
        painter.drawLine(content.left(), content.center().y(), content.right(), content.center().y())

        for region in self._regions:
            rect = self._region_rect(region)
            selected = region.region_id == self._selected_region_id
            hovered = region.region_id == self._hovered_region_id
            fill = QColor(tokens["pair_background"])
            fill.setAlpha(230 if selected else 175 if hovered else 135)
            border = QColor(tokens["pair_accent"] if selected else tokens["pair_border"])
            painter.setPen(QPen(border, 2 if selected else 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 6, 6)

            if rect.width() >= 92:
                painter.setPen(QColor(tokens["text"]))
                painter.drawText(
                    rect.adjusted(12, 0, -22 if hovered else -12, 0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"{format_duration(region.start_ms)} - {format_duration(region.end_ms)}",
                )
            if hovered and rect.width() >= 34:
                close = self._close_rect(rect)
                painter.setPen(QPen(QColor(tokens["muted"]), 1.8))
                painter.drawLine(close.topLeft(), close.bottomRight())
                painter.drawLine(close.topRight(), close.bottomLeft())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        hit = self._region_at(event.position().toPoint())
        if hit is None:
            self._selected_region_id = ""
            self.region_activated.emit("")
            self.update()
            return
        region, rect = hit
        self._selected_region_id = region.region_id
        self.region_activated.emit(region.region_id)
        if rect.width() >= 34 and self._close_rect(rect).contains(event.position()):
            self.region_remove_requested.emit(region.region_id)
            return
        self.seek_requested.emit(region.start_ms)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hit = self._region_at(event.position().toPoint())
        hovered = hit[0].region_id if hit is not None else ""
        if hovered != self._hovered_region_id:
            self._hovered_region_id = hovered
            self.update()
        if hit is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered_region_id = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def _content_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(19, 6, -19, -6)

    def _region_rect(self, region: VocalReferenceRegion) -> QRectF:
        content = self._content_rect()
        if self._duration_ms <= 0:
            return QRectF(content.left(), content.top(), 1, content.height())
        left = content.left() + content.width() * region.start_ms / self._duration_ms
        right = content.left() + content.width() * region.end_ms / self._duration_ms
        return QRectF(left, content.top(), max(2.0, right - left), content.height())

    def _region_at(self, point: QPoint) -> tuple[VocalReferenceRegion, QRectF] | None:
        for region in reversed(self._regions):
            rect = self._region_rect(region).adjusted(-2, 0, 2, 0)
            if rect.contains(point):
                return region, rect.adjusted(2, 0, -2, 0)
        return None

    @staticmethod
    def _close_rect(rect: QRectF) -> QRectF:
        return QRectF(rect.right() - 17, rect.top() + 7, 9, 9)
