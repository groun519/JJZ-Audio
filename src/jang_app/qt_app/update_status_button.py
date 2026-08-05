from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.widgets import FeedbackButton, render_app_icon
from jang_app.services.i18n import tr


UPDATE_BUTTON_WIDTH = 206
UPDATE_BUTTON_HEIGHT = 44
UPDATE_BUTTON_EDGE_MARGIN = 16
UPDATE_BUTTON_STACK_GAP = 10

STATE_AVAILABLE = "available"
STATE_DOWNLOADING = "downloading"
STATE_READY = "ready"
STATE_FAILED = "failed"


def update_button_position(
    parent_height: int,
    button_height: int,
    *,
    anchor_tops: tuple[int, ...] = (),
) -> tuple[int, int]:
    anchor_top = min(anchor_tops) if anchor_tops else parent_height
    y_position = anchor_top - button_height - (
        UPDATE_BUTTON_STACK_GAP if anchor_tops else UPDATE_BUTTON_EDGE_MARGIN
    )
    return UPDATE_BUTTON_EDGE_MARGIN, max(UPDATE_BUTTON_EDGE_MARGIN, y_position)


class UpdateStatusButton(FeedbackButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("UpdateStatusButton")
        self.setFixedSize(UPDATE_BUTTON_WIDTH, UPDATE_BUTTON_HEIGHT)
        self._theme_mode = "white"
        self._state = STATE_AVAILABLE
        self._version = ""
        self._runtime_only = False
        self._progress = 0
        self.setText("")
        self.hide()

    @property
    def state(self) -> str:
        return self._state

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_available(self, version: str, *, runtime_only: bool = False) -> None:
        self._state = STATE_AVAILABLE
        self._version = version
        self._runtime_only = runtime_only
        self._progress = 0
        self._sync_accessibility()

    def set_downloading(self, progress: int = 0) -> None:
        self._state = STATE_DOWNLOADING
        self.set_progress(progress)

    def set_progress(self, progress: int) -> None:
        self._progress = max(0, min(100, int(progress)))
        self._sync_accessibility()

    def set_ready(self) -> None:
        self._state = STATE_READY
        self._progress = 100
        self._sync_accessibility()

    def set_failed(self) -> None:
        self._state = STATE_FAILED
        self._sync_accessibility()

    def apply_language(self) -> None:
        self._sync_accessibility()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = theme_tokens(self._theme_mode)
        hovered = self._is_pointer_hovered()
        pressed = self._is_pointer_pressed() or self.isDown()
        background = tokens["pressed"] if pressed else tokens["hover"] if hovered else tokens["raised"]
        border = tokens["button_border"] if self._state == STATE_READY else tokens["border"]
        text_color = tokens["text"]

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 12, 12)

        icon_key = "refresh" if self._state == STATE_READY else "download"
        render_app_icon(
            painter,
            QRectF(rect.left() + 12, rect.top() + 11, 20, 20),
            icon_key,
            QColor(text_color),
        )
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QColor(text_color))
        painter.drawText(
            QRectF(rect.left() + 42, rect.top(), rect.width() - 54, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._label(),
        )

        if self._state == STATE_DOWNLOADING:
            track = QRectF(rect.left() + 12, rect.bottom() - 5, rect.width() - 24, 2)
            painter.fillRect(track, QColor(tokens["border"]))
            fill = QRectF(track.left(), track.top(), track.width() * self._progress / 100, track.height())
            painter.fillRect(fill, QColor(tokens["text"]))
        self._draw_keyboard_focus(painter, rect, 12)

    def _label(self) -> str:
        if self._state == STATE_DOWNLOADING:
            return tr("Downloading update {progress}%", progress=self._progress)
        if self._state == STATE_READY:
            return tr("Restart to update")
        if self._state == STATE_FAILED:
            return tr("Update failed - retry")
        if self._runtime_only:
            return tr("GPU runtime update")
        return tr("Update {version}", version=self._version)

    def _sync_accessibility(self) -> None:
        label = self._label()
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.update()
