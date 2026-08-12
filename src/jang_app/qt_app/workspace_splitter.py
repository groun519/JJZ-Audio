from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget


WORKSPACE_SPLITTER_HANDLE_WIDTH = 6
_RESTING_STRENGTH = 0.10
_HOVER_STRENGTH = 0.62
_PRESSED_STRENGTH = 0.88
_FADE_DURATION_MS = 140


class WorkspaceSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return SoftWorkspaceSplitterHandle(self.orientation(), self)


class SoftWorkspaceSplitterHandle(QSplitterHandle):
    """Wide hit target with a subtle divider that fades in on interaction."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
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
        palette = self.palette()
        background = QColor(palette.color(QPalette.ColorRole.Window))
        foreground = QColor(palette.color(QPalette.ColorRole.WindowText))
        line_color = _blend_color(
            background,
            foreground,
            self._visual_strength * 0.34,
        )
        grip_color = _blend_color(
            background,
            foreground,
            self._visual_strength,
        )
        rect = QRectF(self.rect())

        painter.setPen(Qt.PenStyle.NoPen)
        if self.orientation() == Qt.Orientation.Horizontal:
            center = rect.center().x()
            painter.fillRect(QRectF(center - 0.5, 8, 1, max(0.0, rect.height() - 16)), line_color)
            if self._visual_strength > 0.18:
                painter.setBrush(grip_color)
                painter.drawRoundedRect(
                    QRectF(center - 1.5, rect.center().y() - 10, 3, 20),
                    1.5,
                    1.5,
                )
        else:
            center = rect.center().y()
            painter.fillRect(QRectF(8, center - 0.5, max(0.0, rect.width() - 16), 1), line_color)
            if self._visual_strength > 0.18:
                painter.setBrush(grip_color)
                painter.drawRoundedRect(
                    QRectF(rect.center().x() - 10, center - 1.5, 20, 3),
                    1.5,
                    1.5,
                )

    def _animate_to(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._visual_strength)
        self._animation.setEndValue(target)
        self._animation.start()


def _blend_color(background: QColor, foreground: QColor, strength: float) -> QColor:
    amount = max(0.0, min(1.0, strength))
    return QColor(
        round(background.red() + (foreground.red() - background.red()) * amount),
        round(background.green() + (foreground.green() - background.green()) * amount),
        round(background.blue() + (foreground.blue() - background.blue()) * amount),
    )


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
