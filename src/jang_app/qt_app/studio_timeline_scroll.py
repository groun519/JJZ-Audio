from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea


class StudioTimelineScrollArea(QScrollArea):
    """Timeline scroller with horizontal navigation on Ctrl + wheel."""

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            pixel_delta = event.pixelDelta().y() or event.pixelDelta().x()
            if pixel_delta:
                distance = pixel_delta
            else:
                angle_delta = event.angleDelta().y() or event.angleDelta().x()
                if not angle_delta:
                    super().wheelEvent(event)
                    return
                distance = round(angle_delta / 120 * max(80, self.viewport().width() // 8))
            scroll_bar = self.horizontalScrollBar()
            scroll_bar.setValue(scroll_bar.value() - distance)
            event.accept()
            return
        super().wheelEvent(event)
