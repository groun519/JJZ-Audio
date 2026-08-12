from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.waveform_thumbnail import WaveformThumbnail


class SoundPoolItemCard(QFrame):
    """Shared sound-card surface; workspace-specific behavior stays in subclasses."""

    activated = Signal(str)

    def __init__(
        self,
        card_id: str,
        *,
        role: str,
        path: Path,
        title: str,
        badge: str,
        detail: str = "",
        duration_ms: int | None = None,
        media_kind: str = "audio",
        object_name: str = "SoundPoolItemCard",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.card_id = card_id
        self.role = role
        self.path = path
        self.media_kind = media_kind
        self._theme_mode = "white"
        self._list_mode = False

        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("role", role)
        self.setProperty("selected", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self.role_strip = QFrame()
        self.role_strip.setObjectName("StudioSoundRoleStrip")
        self.role_strip.setProperty("role", role)
        self.role_strip.setFixedHeight(2)

        self.waveform = WaveformThumbnail(point_count=180, height=40)
        self.waveform.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.video_thumbnail = QLabel("VIDEO")
        self.video_thumbnail.setObjectName("StudioVideoThumbnail")
        self.video_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_thumbnail.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.preview_widget = (
            self.video_thumbnail if media_kind == "video" else self.waveform
        )
        if media_kind != "video":
            self.waveform.set_path(path)

        self.title_label = OverflowTextLabel(
            object_name="StudioSoundCardTitle",
            fixed_height=20,
        )
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.source_badge = QLabel()
        self.source_badge.setObjectName("StudioSoundSourceBadge")
        self.source_badge.setProperty("role", role)
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(52)
        self.source_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.detail_label = QLabel()
        self.detail_label.setObjectName("StudioSoundCardDetail")
        self.detail_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.detail_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.duration_label = QLabel()
        self.duration_label.setObjectName("StudioSoundDuration")
        self.duration_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(7)
        meta_row.addWidget(self.source_badge)
        meta_row.addWidget(self.detail_label, 1)
        meta_row.addWidget(self.duration_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(5)
        layout.addWidget(self.role_strip)
        layout.addWidget(self.preview_widget)
        layout.addWidget(self.title_label)
        layout.addLayout(meta_row)
        self.set_content(
            title=title,
            badge=badge,
            detail=detail,
            duration_ms=duration_ms,
        )

    def set_content(
        self,
        *,
        title: str,
        badge: str,
        detail: str = "",
        duration_ms: int | None = None,
    ) -> None:
        self.title_label.setText(title)
        self.source_badge.setText(badge)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(True)
        self.duration_label.setText(
            _format_time(duration_ms) if duration_ms is not None else ""
        )
        self.duration_label.setVisible(duration_ms is not None)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_list_mode(self, enabled: bool) -> None:
        self._list_mode = bool(enabled)
        self.setProperty("viewMode", "list" if enabled else "grid")
        self.waveform.setFixedHeight(24 if enabled else 40)
        self.video_thumbnail.setFixedHeight(24 if enabled else 40)
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(*(7, 6, 7, 6) if enabled else (8, 7, 8, 8))
            layout.setSpacing(3 if enabled else 5)
        self.setMinimumHeight(88 if enabled else 108)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.waveform.set_theme_mode(theme_mode)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.card_id)
        super().mousePressEvent(event)


def _format_time(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"
