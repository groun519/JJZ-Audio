from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QSizePolicy, QWidget


class HorizontalReveal(QWidget):
    """A layout slot that reveals its contents by expanding horizontally."""

    def __init__(
        self,
        expanded_width: int,
        *,
        duration_ms: int = 180,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded_width = max(1, int(expanded_width))
        self._revealed: bool | None = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.hide()

        self._animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._animation.setDuration(max(0, int(duration_ms)))
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._finish_animation)

    def set_revealed(self, is_revealed: bool, *, animated: bool = True) -> None:
        revealed = bool(is_revealed)
        target_width = self._expanded_width if revealed else 0
        if revealed == self._revealed and self.maximumWidth() == target_width:
            return

        self._revealed = revealed
        self._animation.stop()
        if revealed:
            self.show()

        if not animated or self._animation.duration() == 0:
            self.setMaximumWidth(target_width)
            self.setVisible(revealed)
            return

        self._animation.setStartValue(max(0, min(self.width(), self._expanded_width)))
        self._animation.setEndValue(target_width)
        self._animation.start()

    def is_revealed(self) -> bool:
        return self._revealed is True

    def expanded_width(self) -> int:
        return self._expanded_width

    def _finish_animation(self) -> None:
        if self._revealed is not True:
            self.hide()
