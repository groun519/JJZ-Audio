from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QWidget

from jang_app.qt_app.window_lifecycle import allow_top_level_window


class AppOverlayFrame(QFrame):
    """Frameless app-owned overlay that can stack above native media surfaces."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        allow_top_level_window(self)
