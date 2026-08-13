from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

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
        self._hovered = False
        self._title_text = title
        self._detail_text = detail
        self._list_category_text = title
        self._list_name_text = detail
        self._action_widget: QWidget | None = None
        self._action_slot: QWidget | None = None

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
        self.video_thumbnail = _MediaThumbnail(path, media_kind)
        self.video_thumbnail.setObjectName("StudioVideoThumbnail")
        self.video_thumbnail.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.preview_widget = (
            self.video_thumbnail if media_kind in {"video", "image"} else self.waveform
        )
        if media_kind == "audio":
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

        self.content_layout = QGridLayout(self)
        self.content_layout.setContentsMargins(8, 7, 8, 8)
        self.content_layout.setHorizontalSpacing(7)
        self.content_layout.setVerticalSpacing(5)
        self._arrange_content()
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
        list_category: str | None = None,
        list_name: str | None = None,
    ) -> None:
        self._title_text = title
        self._detail_text = detail
        self._list_category_text = list_category if list_category is not None else title
        self._list_name_text = list_name if list_name is not None else detail
        self.source_badge.setText(badge)
        self.duration_label.setText(
            _format_time(duration_ms) if duration_ms is not None else ""
        )
        self.duration_label.setVisible(duration_ms is not None)
        self._sync_mode_content()

    def set_action_widget(self, widget: QWidget) -> None:
        if self._action_widget is widget:
            return
        if self._action_slot is None:
            self._action_slot = QWidget(self)
            self._action_slot.setObjectName("SoundPoolActionSlot")
            self._action_slot.setFixedSize(widget.size())
            slot_layout = QHBoxLayout(self._action_slot)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.addWidget(widget)
        else:
            layout = self._action_slot.layout()
            if layout is not None:
                while layout.count():
                    layout.takeAt(0)
                layout.addWidget(widget)
            self._action_slot.setFixedSize(widget.size())
        widget.setParent(self._action_slot)
        self._action_widget = widget
        if hasattr(widget, "set_theme_mode"):
            widget.set_theme_mode(self._theme_mode)
        self._arrange_content()
        self._sync_action_visibility()

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
        self._arrange_content()
        self._sync_mode_content()
        self.style().unpolish(self)
        self.style().polish(self)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.waveform.set_theme_mode(theme_mode)
        if self._action_widget is not None and hasattr(self._action_widget, "set_theme_mode"):
            self._action_widget.set_theme_mode(theme_mode)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.card_id)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._sync_action_visibility()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._sync_action_visibility()
        super().leaveEvent(event)

    def _arrange_content(self) -> None:
        while self.content_layout.count():
            self.content_layout.takeAt(0)
        for column in range(5):
            self.content_layout.setColumnStretch(column, 0)

        if self._list_mode:
            self.content_layout.setContentsMargins(8, 6, 8, 6)
            self.content_layout.setHorizontalSpacing(9)
            self.role_strip.hide()
            self.preview_widget.hide()
            self.content_layout.addWidget(self.source_badge, 0, 0)
            self.content_layout.addWidget(self.title_label, 0, 1)
            self.content_layout.addWidget(self.detail_label, 0, 2)
            self.content_layout.addWidget(self.duration_label, 0, 3)
            if self._action_slot is not None:
                self.content_layout.addWidget(self._action_slot, 0, 4)
            self.content_layout.setColumnStretch(1, 3)
            self.content_layout.setColumnStretch(2, 5)
            self.setFixedHeight(48)
            return

        self.content_layout.setContentsMargins(8, 7, 8, 8)
        self.content_layout.setHorizontalSpacing(7)
        self.content_layout.setVerticalSpacing(5)
        self.role_strip.show()
        self.preview_widget.show()
        self.content_layout.addWidget(self.role_strip, 0, 0, 1, 5)
        self.content_layout.addWidget(self.preview_widget, 1, 0, 1, 5)
        self.content_layout.addWidget(self.title_label, 2, 0, 1, 4)
        if self._action_slot is not None:
            self.content_layout.addWidget(self._action_slot, 2, 4)
        self.content_layout.addWidget(self.source_badge, 3, 0)
        self.content_layout.addWidget(self.detail_label, 3, 1, 1, 3)
        self.content_layout.addWidget(self.duration_label, 3, 4)
        self.content_layout.setColumnStretch(1, 1)
        self.setMinimumHeight(108)
        self.setMaximumHeight(16_777_215)

    def _sync_mode_content(self) -> None:
        self.title_label.setText(
            self._list_category_text if self._list_mode else self._title_text
        )
        self.detail_label.setText(
            self._list_name_text if self._list_mode else self._detail_text
        )
        self.detail_label.setVisible(bool(self.detail_label.text()))

    def _sync_action_visibility(self) -> None:
        if self._action_widget is not None:
            self._action_widget.setVisible(self._hovered or self.hasFocus())


class _MediaThumbnail(QLabel):
    def __init__(self, path: Path, media_kind: str) -> None:
        super().__init__("VIDEO" if media_kind == "video" else "IMAGE")
        self._source = QPixmap(str(path)) if media_kind == "image" else QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(40)
        self._refresh_pixmap()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        self.setPixmap(
            self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _format_time(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"
