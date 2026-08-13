from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPalette
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget


WORKSPACE_SPLITTER_HANDLE_WIDTH = 6
_RESTING_STRENGTH = 0.0
_HOVER_STRENGTH = 0.52
_PRESSED_STRENGTH = 0.76
_FADE_DURATION_MS = 140
_EDGE_INSET = 12.0


class WorkspaceSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return SoftWorkspaceSplitterHandle(self.orientation(), self)


class SoftWorkspaceSplitterHandle(QSplitterHandle):
    """Wide hit target with a subtle divider that fades in on interaction."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setCursor(
            Qt.CursorShape.SplitHCursor
            if orientation == Qt.Orientation.Horizontal
            else Qt.CursorShape.SplitVCursor
        )
        self._visual_strength = _RESTING_STRENGTH
        self._pressed = False
        self._animation = QPropertyAnimation(self, b"visualStrength", self)
        self._animation.setDuration(_FADE_DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def visual_strength(self) -> float:
        return self._visual_strength

    def set_visual_strength(self, value: float) -> None:
        self._visual_strength = max(0.0, min(1.0, float(value)))
        self.update()

    visualStrength = Property(float, visual_strength, set_visual_strength)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_to(_HOVER_STRENGTH)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._pressed:
            self._animate_to(_RESTING_STRENGTH)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._animate_to(_PRESSED_STRENGTH)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self._animate_to(
            _HOVER_STRENGTH if self.underMouse() else _RESTING_STRENGTH
        )
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        if self._visual_strength <= 0.001 or rect.isEmpty():
            return

        edge_color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        edge_color.setAlpha(round(255 * self._visual_strength * 0.15))
        soft_color = QColor(edge_color)
        soft_color.setAlpha(round(255 * self._visual_strength * 0.055))
        clear_color = QColor(edge_color)
        clear_color.setAlpha(0)

        if self.orientation() == Qt.Orientation.Horizontal:
            visual_rect = rect.adjusted(0, _EDGE_INSET, 0, -_EDGE_INSET)
            gradient = QLinearGradient(visual_rect.left(), 0, visual_rect.right(), 0)
        else:
            visual_rect = rect.adjusted(_EDGE_INSET, 0, -_EDGE_INSET, 0)
            gradient = QLinearGradient(0, visual_rect.top(), 0, visual_rect.bottom())
        if visual_rect.isEmpty():
            return
        gradient.setColorAt(0.0, edge_color)
        gradient.setColorAt(0.28, soft_color)
        gradient.setColorAt(0.5, clear_color)
        gradient.setColorAt(0.72, soft_color)
        gradient.setColorAt(1.0, edge_color)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(visual_rect, 3.0, 3.0)

    def _animate_to(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._visual_strength)
        self._animation.setEndValue(target)
        self._animation.start()

def create_workspace_splitter(
    panels: Sequence[QWidget],
    *,
    object_name: str,
    orientation: Qt.Orientation = Qt.Orientation.Horizontal,
    sizes: Sequence[int] = (),
    stretch_factors: Sequence[int] = (),
    collapsible: bool | Sequence[bool] = False,
) -> QSplitter:
    """Build the shared draggable panel divider used by workspace pages."""
    panel_list = tuple(panels)
    if not panel_list:
        raise ValueError("A workspace splitter requires at least one panel.")
    if sizes and len(sizes) != len(panel_list):
        raise ValueError("Splitter sizes must match the panel count.")
    if stretch_factors and len(stretch_factors) != len(panel_list):
        raise ValueError("Splitter stretch factors must match the panel count.")

    if isinstance(collapsible, bool):
        collapsible_flags = (collapsible,) * len(panel_list)
    else:
        collapsible_flags = tuple(collapsible)
        if len(collapsible_flags) != len(panel_list):
            raise ValueError("Splitter collapsible flags must match the panel count.")

    splitter = WorkspaceSplitter(orientation)
    splitter.setObjectName(object_name)
    splitter.setProperty("workspaceSplitter", True)
    splitter.setChildrenCollapsible(any(collapsible_flags))
    splitter.setHandleWidth(WORKSPACE_SPLITTER_HANDLE_WIDTH)

    for index, panel in enumerate(panel_list):
        splitter.addWidget(panel)
        splitter.setCollapsible(index, collapsible_flags[index])
        if stretch_factors:
            splitter.setStretchFactor(index, stretch_factors[index])

    if sizes:
        splitter.setSizes(list(sizes))
    return splitter
