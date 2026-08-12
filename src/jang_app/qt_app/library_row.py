from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from jang_app.qt_app.horizontal_reveal import HorizontalReveal
from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTitleLabel
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.waveform_thumbnail import WaveformThumbnail
from jang_app.qt_app.widgets import (
    COMPACT_ICON_BUTTON_SIZE,
    DangerIconButton,
    FeedbackButton,
    SvgIconButton,
)
from jang_app.services.i18n import tr
from jang_app.services.song_metadata import SongDisplayMetadata


class WorkSongRevealButton(SvgIconButton):
    """Work-song action with a lightweight perimeter loading indicator."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("pin", size=34)
        self.setParent(parent)
        self._loading = False
        self._loading_phase = 0.0
        self._loading_color = QColor("#765814")
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(24)
        self._loading_timer.timeout.connect(self._advance_loading_border)

    def set_theme_mode(self, theme_mode: str) -> None:
        super().set_theme_mode(theme_mode)
        self._loading_color = QColor("#e7d3a0" if theme_mode == "dark" else "#765814")
        self.update()

    def _icon_key(self) -> str:
        return "pin_filled" if self.isChecked() else "pin"

    def set_loading(self, is_loading: bool) -> None:
        loading = bool(is_loading)
        if loading == self._loading:
            return
        self._loading = loading
        self.setProperty("loading", loading)
        self.setEnabled(not loading)
        if loading:
            self._loading_timer.start()
        else:
            self._loading_timer.stop()
            self._loading_phase = 0.0
        self.update()

    def is_loading(self) -> bool:
        return self._loading

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._loading:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), 9, 9)
        start = self._loading_phase % 1.0
        span = 0.28
        steps = 28
        previous_t = start
        previous = outline.pointAtPercent(previous_t)
        for index in range(1, steps + 1):
            current_t = (start + span * index / steps) % 1.0
            current = outline.pointAtPercent(current_t)
            if current_t >= previous_t:
                color = QColor(self._loading_color)
                color.setAlpha(55 + round(200 * index / steps))
                pen = QPen(color, 2.4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QPointF(previous), QPointF(current))
            previous_t = current_t
            previous = current

    def _advance_loading_border(self) -> None:
        self._loading_phase = (self._loading_phase + 0.025) % 1.0
        self.update()


class SongListRow(QWidget):
    rename_requested = Signal(str, str)
    remove_requested = Signal(str)
    work_song_toggled = Signal(str)
    details_requested = Signal(str)
    preview_requested = Signal(str)
    preview_play_toggled = Signal(str)
    preview_seek_requested = Signal(str, int)
    preview_height_changed = Signal(str)

    def __init__(
        self,
        item_id: str,
        title: str,
        metadata: SongDisplayMetadata,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SongListRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("workSong", False)
        self.setProperty("workSongPulse", False)
        self._item_id = item_id
        self._is_editing = False
        self._is_hovered = False
        self._is_work_song = False
        self._preview_expanded = False
        self.setMouseTracking(True)

        self.source_badge = QLabel()
        set_translated_text(self.source_badge, metadata.source_label)
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setProperty("sourceType", metadata.source_type)
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(52)

        self.title_label = OverflowTitleLabel(title)

        self.title_edit = QLineEdit(title)
        self.title_edit.setObjectName("InlineTitleEdit")
        self.title_edit.hide()
        self.title_edit.returnPressed.connect(self._commit_rename)
        self.title_edit.editingFinished.connect(self._commit_rename)

        self.metadata_label = QLabel(metadata.detail_label)
        self.metadata_label.setObjectName("LibraryRowMeta")

        self.waveform = WaveformThumbnail(minimum_width=190)
        self.waveform.set_path(metadata.waveform_path)

        self.work_song_button = WorkSongRevealButton()
        self.work_song_button.setObjectName("WorkSongRevealButton")
        self.work_song_button.setCheckable(True)
        set_translated_tooltip(self.work_song_button, "Set as work song")
        self.work_song_button.setAccessibleName(tr("Set as work song"))
        self.work_song_button.clicked.connect(
            lambda: self.work_song_toggled.emit(self._item_id)
        )
        self.work_song_reveal = HorizontalReveal(44)
        self.work_song_reveal.setObjectName("WorkSongRevealSlot")
        work_song_layout = QHBoxLayout(self.work_song_reveal)
        work_song_layout.setContentsMargins(0, 0, 10, 0)
        work_song_layout.setSpacing(0)
        work_song_layout.addWidget(self.work_song_button)

        self.details_button = SvgIconButton("database", size=COMPACT_ICON_BUTTON_SIZE)
        set_translated_tooltip(self.details_button, "Open song details")
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self._item_id))
        self.rename_button = SvgIconButton("edit", size=COMPACT_ICON_BUTTON_SIZE)
        set_translated_tooltip(self.rename_button, "Rename")
        self.rename_button.clicked.connect(self._begin_rename)
        self.remove_button = DangerIconButton(size=COMPACT_ICON_BUTTON_SIZE)
        set_translated_tooltip(self.remove_button, "Remove")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self._item_id))
        self.secondary_action_buttons = (
            self.details_button,
            self.rename_button,
            self.remove_button,
        )
        self.action_buttons = (
            *self.secondary_action_buttons,
        )

        action_container = QWidget()
        action_container.setObjectName("SongActionSlot")
        action_spacing = 7
        action_container.setFixedWidth(
            len(self.action_buttons) * COMPACT_ICON_BUTTON_SIZE
            + (len(self.action_buttons) - 1) * action_spacing
        )
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(action_spacing)
        for button in self.action_buttons:
            action_layout.addWidget(button)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.title_edit)
        text_layout.addWidget(self.metadata_label)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)
        body_layout.addWidget(self.work_song_reveal, 0)
        body_layout.addWidget(self.source_badge, 0)
        body_layout.addLayout(text_layout, 2)
        body_layout.addWidget(self.waveform, 3)
        body_layout.addWidget(action_container, 0)

        self.preview_divider = QFrame()
        self.preview_divider.setObjectName("LibraryPreviewDivider")
        self.preview_divider.setFixedHeight(1)
        self.preview_divider.hide()

        self.preview_transport = TransportControls()
        self.preview_transport.setObjectName("LibraryPreviewTransport")
        self.preview_transport.play_toggled.connect(
            lambda: self.preview_play_toggled.emit(self._item_id)
        )
        self.preview_transport.seek_requested.connect(
            lambda position_ms: self.preview_seek_requested.emit(self._item_id, position_ms)
        )
        self.preview_transport.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)
        layout.addLayout(body_layout)
        layout.addWidget(self.preview_divider)
        layout.addWidget(self.preview_transport)

        self._sync_action_visibility()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 138 if self._preview_expanded else 84)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.work_song_button.set_theme_mode(theme_mode)
        self.waveform.set_theme_mode(theme_mode)
        self.preview_transport.set_theme_mode(theme_mode)
        for button in self.action_buttons:
            button.set_theme_mode(theme_mode)

    def set_preview_expanded(self, is_expanded: bool) -> None:
        if self._preview_expanded == is_expanded:
            return
        self._preview_expanded = is_expanded
        self.preview_divider.setVisible(is_expanded)
        self.preview_transport.setVisible(is_expanded)
        if not is_expanded:
            self.preview_transport.set_playing(False)
        self.updateGeometry()
        self.preview_height_changed.emit(self._item_id)

    def is_preview_expanded(self) -> bool:
        return self._preview_expanded

    def set_preview_queue(self, duration_ms: int) -> None:
        self.preview_transport.set_duration(duration_ms)
        self.preview_transport.set_position(0, duration_ms)

    def clear_preview(self) -> None:
        self.preview_transport.clear()

    def set_preview_playing(self, is_playing: bool) -> None:
        self.preview_transport.set_playing(is_playing)

    def set_preview_position(self, position_ms: int, duration_ms: int) -> None:
        self.preview_transport.set_position(position_ms, duration_ms)

    def set_work_song_active(self, is_active: bool) -> None:
        active = bool(is_active)
        if active == self._is_work_song:
            return
        changed = active != self._is_work_song
        self._is_work_song = active
        self.work_song_button.setChecked(active)
        self.setProperty("workSong", active)
        tooltip = "Clear work song" if active else "Set as work song"
        set_translated_tooltip(self.work_song_button, tooltip)
        self.work_song_button.setAccessibleName(tr(tooltip))
        if active and changed:
            self.setProperty("workSongPulse", True)
            QTimer.singleShot(450, self._finish_work_song_pulse)
        elif not active:
            self.setProperty("workSongPulse", False)
        self._refresh_style()
        self._sync_action_visibility()

    def is_work_song_active(self) -> bool:
        return self._is_work_song

    def set_work_song_loading(self, is_loading: bool) -> None:
        self.work_song_button.set_loading(is_loading)
        self._sync_action_visibility()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = True
        self._sync_action_visibility()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = False
        if not self._is_editing:
            self._sync_action_visibility()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self._is_editing:
            self.preview_requested.emit(self._item_id)
        super().mouseReleaseEvent(event)

    def _sync_action_visibility(self) -> None:
        show_hover_actions = self._is_hovered or self._is_editing
        self.work_song_reveal.set_revealed(
            show_hover_actions or self._is_work_song or self.work_song_button.is_loading(),
            animated=self.isVisible(),
        )
        for button in self.secondary_action_buttons:
            button.setVisible(show_hover_actions)

    def _begin_rename(self) -> None:
        self._is_editing = True
        self.title_edit.setText(self.title_label.text())
        self.title_label.hide()
        self.title_edit.show()
        self._sync_action_visibility()
        self.title_edit.setFocus(Qt.FocusReason.MouseFocusReason)
        self.title_edit.selectAll()

    def _commit_rename(self) -> None:
        if not self._is_editing:
            return
        self._is_editing = False
        next_title = self.title_edit.text().strip()
        current_title = self.title_label.text()
        self.title_edit.hide()
        self.title_label.show()
        self._sync_action_visibility()
        if next_title and next_title != current_title:
            self.rename_requested.emit(self._item_id, next_title)
        else:
            self.title_edit.setText(current_title)

    def _finish_work_song_pulse(self) -> None:
        if not self.property("workSongPulse"):
            return
        self.setProperty("workSongPulse", False)
        self._refresh_style()

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
