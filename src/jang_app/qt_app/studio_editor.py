from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import uuid

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.studio_sound_pool import STUDIO_ASSET_MIME, StudioSoundPool
from jang_app.qt_app.studio_fx_pool import STUDIO_EFFECT_MIME, StudioFxPool
from jang_app.qt_app.studio_inspector import StudioInspector
from jang_app.qt_app.widgets import danger_icon_button_palette, render_app_icon
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.qt_app.theme import theme_tokens
from jang_app.services.i18n import tr
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_AUDIO,
    TRACK_VIDEO,
    StudioClip,
    StudioEffect,
    StudioSession,
    StudioTrack,
)
from jang_app.services.snapshot_history import SnapshotHistory
from jang_app.services.studio_timeline import (
    StudioTimelineError,
    add_studio_clip,
    add_studio_clip_effect,
    add_studio_track,
    move_studio_clip,
    remove_studio_clip,
    remove_studio_clip_effect,
    remove_studio_track,
    session_duration_ms,
    set_studio_clip_mix,
    set_studio_track_collapsed,
    set_studio_track_name,
    set_studio_track_mix,
    split_studio_clip,
    trim_studio_clip,
    update_studio_clip_effect,
)
from jang_app.services.waveform import build_waveform_peaks, waveform_cache_key


_WAVEFORM_POINTS = 900
_WAVEFORM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="studio-waveform")
_WAVEFORM_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
_ROLE_COLORS = {
    "original_vocal": QColor("#d6a85f"),
    "instrumental": QColor("#58a88f"),
    "converted_vocal": QColor("#d2675a"),
    "audio": QColor("#7788bb"),
    "video": QColor("#668cc4"),
}


class StudioTimelineView(QWidget):
    clip_selected = Signal(str)
    track_selected = Signal(str)
    clip_moved = Signal(str, str, int)
    clip_trimmed = Signal(str, int, int, bool)
    asset_dropped = Signal(str, str, int)
    effect_dropped = Signal(str, str)
    effect_selected = Signal(str, str)
    effect_remove_requested = Signal(str, str)
    track_mix_changed = Signal(str, bool, bool, int)
    track_add_requested = Signal()
    track_remove_requested = Signal(str)
    track_collapsed_changed = Signal(str, bool)
    seek_requested = Signal(int)
    clip_split_requested = Signal(str, int)
    _peaks_ready = Signal(object, object)

    HEADER_WIDTH = 184
    RULER_HEIGHT = 34
    LANE_HEIGHT = 98
    COLLAPSED_LANE_HEIGHT = 42
    ADD_TRACK_HEIGHT = 48
    HANDLE_WIDTH = 7

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StudioTimelineView")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumHeight(330)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._session = StudioSession()
        self._theme_mode = "dark"
        self._theme = theme_tokens("dark")
        self._assets: dict[str, StudioSoundAsset] = {}
        self._peaks: dict[str, list[float]] = {}
        self._pending_peak_keys: set[tuple[str, int, int, int]] = set()
        self._pixels_per_second = 7
        self._horizontal_offset = 0
        self._vertical_offset = 0
        self._playhead_ms = 0
        self._split_mode = False
        self._split_hover: tuple[str, int] | None = None
        self._hover_effect: tuple[str, str] | None = None
        self._effect_drop_clip_id = ""
        self._selected_clip_id = ""
        self._selected_track_id = ""
        self._drag_mode = ""
        self._drag_origin = QPoint()
        self._drag_track_id = ""
        self._drag_clip: StudioClip | None = None
        self._drag_volume_value: int | None = None
        self._hover_control: tuple[str, str] | None = None
        self._hover_track_id = ""
        self._add_track_hovered = False
        self._waveform_request_timer = QTimer(self)
        self._waveform_request_timer.setSingleShot(True)
        self._waveform_request_timer.setInterval(70)
        self._waveform_request_timer.timeout.connect(self._request_waveforms)
        self._peaks_ready.connect(self._apply_peaks)

    def set_context(
        self,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...],
    ) -> None:
        self._assets = {asset.asset_id: asset for asset in assets}
        self.update_session(session)
        if self.isVisible():
            self._queue_waveform_request()

    def update_session(self, session: StudioSession) -> None:
        """Refresh timeline state without reloading unchanged waveform data."""
        self._session = session
        if self._selected_clip_id and self._clip(self._selected_clip_id) is None:
            self._selected_clip_id = ""
        if self._selected_track_id and self._track(self._selected_track_id) is None:
            self._selected_track_id = ""
        if self._hover_track_id and self._track(self._hover_track_id) is None:
            self._hover_track_id = ""
        self._update_extent()
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._queue_waveform_request()

    def set_zoom(self, pixels_per_second: int) -> None:
        self._pixels_per_second = max(2, min(24, int(pixels_per_second)))
        self._update_extent()
        self.update()

    def set_horizontal_offset(self, offset: int) -> None:
        next_offset = max(0, int(offset))
        if next_offset == self._horizontal_offset:
            return
        self._horizontal_offset = next_offset
        self.update()

    def set_vertical_offset(self, offset: int) -> None:
        next_offset = max(0, int(offset))
        if next_offset == self._vertical_offset:
            return
        self._vertical_offset = next_offset
        self.update()

    def set_playhead(self, position_ms: int) -> None:
        self._playhead_ms = max(0, int(position_ms))
        self.update()

    def set_split_mode(self, enabled: bool) -> None:
        self._split_mode = bool(enabled)
        self._split_hover = None
        self._clear_drag()
        if self._split_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self._theme = theme_tokens(theme_mode)
        self.update()

    def selected_clip_id(self) -> str:
        return self._selected_clip_id

    def selected_track_id(self) -> str:
        return self._selected_track_id

    def select_clip(self, clip_id: str) -> None:
        track = next(
            (
                candidate
                for candidate in self._session.tracks
                if any(clip.clip_id == clip_id for clip in candidate.clips)
            ),
            None,
        )
        if track is None:
            return
        self._selected_clip_id = clip_id
        self._selected_track_id = track.track_id
        self.clip_selected.emit(clip_id)
        self.update()

    def select_track(self, track_id: str) -> None:
        if self._track(track_id) is None:
            return
        self._selected_clip_id = ""
        self._selected_track_id = track_id
        self.track_selected.emit(track_id)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(self._theme["surface"]))
        for index, track in enumerate(self._session.tracks):
            self._paint_track(painter, track, index)
        self._paint_add_track_row(painter)
        self._paint_ruler(painter)
        self._paint_playhead(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        effect_hit = self._effect_at(event.position().toPoint())
        if effect_hit is not None:
            clip, effect, _chip_rect, remove_rect = effect_hit
            self._selected_clip_id = clip.clip_id
            self.clip_selected.emit(clip.clip_id)
            if self._hover_effect == (clip.clip_id, effect.effect_id) and remove_rect.contains(
                event.position()
            ):
                self.effect_remove_requested.emit(clip.clip_id, effect.effect_id)
            else:
                self.effect_selected.emit(clip.clip_id, effect.effect_id)
            event.accept()
            self.update()
            return
        if self._point_in_ruler(event.position().y()):
            if event.position().x() >= self._header_right():
                self.seek_requested.emit(self._x_to_ms(event.position().x()))
            event.accept()
            return
        if self._split_mode:
            hit = self._clip_at(event.position().toPoint())
            if hit is not None:
                track, clip, _rect = hit
                split_position = self._split_position(clip, event.position().x())
                self._selected_track_id = track.track_id
                self._selected_clip_id = clip.clip_id
                self.clip_selected.emit(clip.clip_id)
                if split_position is not None:
                    self.clip_split_requested.emit(clip.clip_id, split_position)
            event.accept()
            self.update()
            return
        if self._add_track_rect().contains(event.position()):
            self.track_add_requested.emit()
            return
        control = self._track_control_at(event.position().toPoint())
        if control is not None:
            track, kind, _rect = control
            if kind == "remove":
                self.track_remove_requested.emit(track.track_id)
                return
            if kind == "collapse":
                self.track_collapsed_changed.emit(track.track_id, not track.collapsed)
                return
            self._selected_track_id = track.track_id
            self._selected_clip_id = ""
            self.track_selected.emit(track.track_id)
            if kind == "mute":
                self.track_mix_changed.emit(
                    track.track_id,
                    not track.muted,
                    track.solo,
                    track.volume_percent,
                )
            elif kind == "volume":
                self._drag_mode = "volume"
                self._drag_track_id = track.track_id
                self._drag_volume_value = self._track_volume_from_x(track, event.position().x())
            self.update()
            return
        hit = self._clip_at(event.position().toPoint())
        if hit is None:
            track = self._track_at_y(event.position().y())
            if track is not None:
                self._selected_track_id = track.track_id
                self._selected_clip_id = ""
                self.track_selected.emit(track.track_id)
            if event.position().x() >= self._header_right():
                self.seek_requested.emit(self._x_to_ms(event.position().x()))
            self.update()
            return

        track, clip, rect = hit
        self._selected_track_id = track.track_id
        self._selected_clip_id = clip.clip_id
        self._drag_origin = event.position().toPoint()
        self._drag_track_id = track.track_id
        self._drag_clip = clip
        if abs(event.position().x() - rect.left()) <= self.HANDLE_WIDTH:
            self._drag_mode = "trim-left"
        elif abs(event.position().x() - rect.right()) <= self.HANDLE_WIDTH:
            self._drag_mode = "trim-right"
        else:
            self._drag_mode = "move"
        self.clip_selected.emit(clip.clip_id)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode == "volume":
            track = self._track(self._drag_track_id)
            if track is not None:
                self._drag_volume_value = self._track_volume_from_x(track, event.position().x())
                self.update()
            return
        if self._drag_clip is None or not self._drag_mode:
            self._update_cursor(event.position().toPoint())
            return super().mouseMoveEvent(event)
        delta_ms = round((event.position().x() - self._drag_origin.x()) * 1000 / self._pixels_per_second)
        if self._drag_mode == "move":
            target = self._track_at_y(event.position().y())
            if target is not None and self._track_accepts_asset(target, self._drag_clip.asset.asset_id):
                self._drag_track_id = target.track_id
            self._drag_clip = replace(
                self._drag_clip,
                timeline_start_ms=max(0, self._original_clip().timeline_start_ms + delta_ms),
            )
        elif self._drag_mode == "trim-left":
            original = self._original_clip()
            start = max(0, min(original.source_end_ms - 100, original.source_start_ms + delta_ms))
            self._drag_clip = replace(
                original,
                source_start_ms=start,
                timeline_start_ms=max(0, original.timeline_start_ms + start - original.source_start_ms),
            )
        elif self._drag_mode == "trim-right":
            original = self._original_clip()
            asset = self._assets.get(original.asset.asset_id)
            source_limit = asset.duration_ms if asset is not None else original.source_end_ms
            end = max(original.source_start_ms + 100, min(source_limit, original.source_end_ms + delta_ms))
            self._drag_clip = replace(original, source_end_ms=end)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode == "volume":
            track = self._track(self._drag_track_id)
            volume = self._drag_volume_value
            self._drag_mode = ""
            self._drag_track_id = ""
            self._drag_volume_value = None
            if track is not None and volume is not None and volume != track.volume_percent:
                self.track_mix_changed.emit(
                    track.track_id,
                    track.muted,
                    track.solo,
                    volume,
                )
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._drag_clip is None:
            return super().mouseReleaseEvent(event)
        clip = self._drag_clip
        mode = self._drag_mode
        target_track = self._drag_track_id
        self._clear_drag()
        if mode == "move":
            self.clip_moved.emit(clip.clip_id, target_track, clip.timeline_start_ms)
        elif mode == "trim-left":
            self.clip_trimmed.emit(clip.clip_id, clip.source_start_ms, clip.source_end_ms, True)
        elif mode == "trim-right":
            self.clip_trimmed.emit(clip.clip_id, clip.source_start_ms, clip.source_end_ms, False)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(STUDIO_ASSET_MIME) or event.mimeData().hasFormat(
            STUDIO_EFFECT_MIME
        ):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(STUDIO_EFFECT_MIME):
            target = self._effect_drop_target(event.position().toPoint())
            next_target = target.clip_id if target is not None else ""
            if next_target != self._effect_drop_clip_id:
                self._effect_drop_clip_id = next_target
                self.update()
            if target is not None:
                event.acceptProposedAction()
            return
        has_asset = event.mimeData().hasFormat(STUDIO_ASSET_MIME)
        asset_id = (
            bytes(event.mimeData().data(STUDIO_ASSET_MIME)).decode("utf-8", errors="ignore")
            if has_asset
            else ""
        )
        track = self._track_at_y(event.position().y())
        if (
            has_asset
            and not self._point_in_header(event.position().x())
            and track is not None
            and self._track_accepts_asset(track, asset_id)
        ):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(STUDIO_EFFECT_MIME):
            target = self._effect_drop_target(event.position().toPoint())
            self._effect_drop_clip_id = ""
            self.update()
            if target is None:
                return
            effect_kind = bytes(event.mimeData().data(STUDIO_EFFECT_MIME)).decode(
                "utf-8", errors="ignore"
            )
            if effect_kind:
                self.effect_dropped.emit(effect_kind, target.clip_id)
                event.acceptProposedAction()
            return
        track = self._track_at_y(event.position().y())
        if (
            track is None
            or self._point_in_header(event.position().x())
            or not event.mimeData().hasFormat(STUDIO_ASSET_MIME)
        ):
            return
        asset_id = bytes(event.mimeData().data(STUDIO_ASSET_MIME)).decode("utf-8", errors="ignore")
        if asset_id and self._track_accepts_asset(track, asset_id):
            self.asset_dropped.emit(asset_id, track.track_id, self._x_to_ms(event.position().x()))
            event.acceptProposedAction()

    def _paint_ruler(self, painter: QPainter) -> None:
        top = self._ruler_top()
        bottom = top + self.RULER_HEIGHT
        painter.fillRect(
            QRectF(0, top, self.width(), self.RULER_HEIGHT),
            QColor(self._theme["raised"]),
        )
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(0, bottom - 1, self.width(), bottom - 1)
        painter.setPen(QColor(self._theme["text"]))
        tick_ms = 10_000 if self._pixels_per_second < 10 else 5_000
        duration = self._visible_duration_ms()
        for position_ms in range(0, duration + tick_ms, tick_ms):
            x = self._ms_to_x(position_ms)
            painter.drawLine(int(x), bottom - 8, int(x), bottom)
            painter.drawText(int(x + 5), top + 21, _format_time(position_ms))
        header_left = self._header_left()
        header_right = self._header_right()
        painter.fillRect(
            QRectF(header_left, top, self.HEADER_WIDTH, self.RULER_HEIGHT),
            QColor(self._theme["raised"]),
        )
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(int(header_right), top, int(header_right), bottom)
        painter.drawLine(int(header_left), bottom - 1, int(header_right), bottom - 1)

    def _paint_track(self, painter: QPainter, track: StudioTrack, index: int) -> None:
        top = self._track_top(index)
        lane_height = self._track_height(track)
        lane = QRectF(0, top, self.width(), lane_height)
        if index % 2:
            painter.fillRect(lane, QColor(self._theme["card"]))
        if self._hover_track_id == track.track_id:
            painter.fillRect(lane, QColor(self._theme["hover"]))
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(0, int(lane.bottom()), self.width(), int(lane.bottom()))

        for clip in track.clips:
            drawn = self._drag_clip if self._drag_clip is not None and clip.clip_id == self._drag_clip.clip_id else clip
            drawn_track_id = self._drag_track_id if drawn is self._drag_clip else track.track_id
            if drawn_track_id != track.track_id:
                continue
            self._paint_clip(painter, track, drawn, index)
        if self._drag_clip is not None and self._drag_track_id == track.track_id:
            original_track = self._track_for_clip(self._drag_clip.clip_id)
            if original_track is not None and original_track.track_id != track.track_id:
                self._paint_clip(painter, track, self._drag_clip, index)

        header_left = self._header_left()
        header_right = self._header_right()
        header_background = (
            self._theme["hover"]
            if self._hover_track_id == track.track_id
            else self._theme["raised"]
        )
        painter.fillRect(
            QRectF(header_left, top, self.HEADER_WIDTH, lane_height),
            QColor(header_background),
        )
        painter.setPen(QColor(self._theme["text"]))
        painter.drawText(
            self._track_title_rect(track, index),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            tr(track.name),
        )
        if self._hover_track_id == track.track_id and track.role == TRACK_AUDIO:
            self._paint_track_remove_button(painter, index)
        self._paint_track_collapse_button(painter, track, index)
        self._paint_track_controls(painter, track, index)
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(int(header_right), top, int(header_right), int(lane.bottom()))
        painter.drawLine(int(header_left), int(lane.bottom()), int(header_right), int(lane.bottom()))
        if self._is_first_added_track(index):
            painter.setPen(QPen(QColor(self._theme["focus"]), 2))
            painter.drawLine(0, int(lane.top()), self.width(), int(lane.top()))

    def _paint_clip(self, painter: QPainter, track: StudioTrack, clip: StudioClip, index: int) -> None:
        rect = self._clip_rect(clip, index)
        color = QColor(_ROLE_COLORS.get(track.role, _ROLE_COLORS["audio"]))
        if track.muted or clip.muted:
            color.setAlpha(70)
        else:
            color.setAlpha(170)
        selected = clip.clip_id == self._selected_clip_id
        drop_target = clip.clip_id == self._effect_drop_clip_id
        painter.setPen(QPen(color.lighter(155) if selected else color.darker(115), 2 if selected else 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 6, 6)
        if track.role == TRACK_VIDEO:
            self._paint_video_clip(painter, rect)
        else:
            self._paint_clip_waveform(painter, clip, rect)
            self._paint_clip_fades(painter, clip, rect)
        painter.setPen(QColor("#f4f1ea"))
        asset = self._assets.get(clip.asset.asset_id)
        label = asset.label if asset is not None else tr("Missing sound")
        painter.drawText(rect.adjusted(10, 5, -10, -5), Qt.AlignmentFlag.AlignTop, label)
        self._paint_clip_effects(painter, clip, index)
        if drop_target:
            painter.setPen(QPen(QColor(self._theme["accent"]), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
        if selected:
            painter.fillRect(QRectF(rect.left(), rect.top(), self.HANDLE_WIDTH, rect.height()), color.lighter(145))
            painter.fillRect(QRectF(rect.right() - self.HANDLE_WIDTH, rect.top(), self.HANDLE_WIDTH, rect.height()), color.lighter(145))
        if self._split_hover is not None and self._split_hover[0] == clip.clip_id:
            split_x = self._ms_to_x(self._split_hover[1])
            painter.setPen(QPen(QColor(self._theme["accent"]), 2))
            painter.drawLine(int(split_x), int(rect.top() + 2), int(split_x), int(rect.bottom() - 2))

    def _paint_clip_effects(self, painter: QPainter, clip: StudioClip, index: int) -> None:
        regions = self._effect_chip_rects(clip, index)
        if not regions:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for effect, chip_rect, remove_rect in regions:
            hovered = self._hover_effect == (clip.clip_id, effect.effect_id)
            painter.setPen(QPen(QColor(self._theme["focus"]), 1))
            painter.setBrush(QColor(self._theme["selection"] if hovered else self._theme["card"]))
            painter.drawRoundedRect(chip_rect, 5, 5)
            painter.setPen(QColor(self._theme["text"]))
            if chip_rect.width() >= 58:
                text_rect = chip_rect.adjusted(6, 0, -18 if hovered else -6, 0)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, tr("Reverb"))
            elif not hovered:
                painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, "FX")
            if hovered:
                painter.drawText(remove_rect, Qt.AlignmentFlag.AlignCenter, "×")
        painter.restore()

    def _effect_chip_rects(
        self,
        clip: StudioClip,
        track_index: int,
    ) -> tuple[tuple[StudioEffect, QRectF, QRectF], ...]:
        if not clip.effects or self._session.tracks[track_index].collapsed:
            return ()
        clip_rect = self._clip_rect(clip, track_index)
        chip_height = min(20.0, max(12.0, clip_rect.height() * 0.28))
        bottom = clip_rect.bottom() - 5
        available = max(8.0, clip_rect.width() - 12)
        if available < 34:
            chip_width = min(12.0, available)
            effects = clip.effects[:1]
        elif available < 76:
            chip_width = min(36.0, available)
            effects = clip.effects[:1]
        else:
            effects = clip.effects[: max(1, int(available // 78))]
            chip_width = min(74.0, max(40.0, available / len(effects) - 4))
        regions: list[tuple[StudioEffect, QRectF, QRectF]] = []
        left = clip_rect.left() + 6
        for effect in effects:
            chip = QRectF(left, bottom - chip_height, chip_width, chip_height)
            remove = QRectF(max(chip.left(), chip.right() - 18), chip.top(), min(18, chip.width()), chip.height())
            regions.append((effect, chip, remove))
            left = chip.right() + 4
        return tuple(regions)

    def _effect_at(
        self,
        point: QPoint,
    ) -> tuple[StudioClip, StudioEffect, QRectF, QRectF] | None:
        hit = self._clip_at(point)
        if hit is None:
            return None
        track, clip, _clip_rect = hit
        index = self._session.tracks.index(track)
        for effect, chip_rect, remove_rect in self._effect_chip_rects(clip, index):
            if chip_rect.contains(point):
                return clip, effect, chip_rect, remove_rect
        return None

    def _effect_drop_target(self, point: QPoint) -> StudioClip | None:
        hit = self._clip_at(point)
        if hit is None or hit[0].role == TRACK_VIDEO:
            return None
        return hit[1]

    def _paint_video_clip(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        frame_width = 54
        x = rect.left() + 8
        while x < rect.right() - 4:
            painter.drawRoundedRect(
                QRectF(x, rect.top() + 24, min(frame_width, rect.right() - x), max(4, rect.height() - 32)),
                3,
                3,
            )
            x += frame_width + 5
        painter.restore()

    def _paint_clip_fades(self, painter: QPainter, clip: StudioClip, rect: QRectF) -> None:
        if clip.duration_ms <= 0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
        if clip.fade_in_ms:
            fade_end = rect.left() + rect.width() * clip.fade_in_ms / clip.duration_ms
            painter.drawLine(
                int(rect.left() + 1),
                int(rect.bottom() - 2),
                int(fade_end),
                int(rect.top() + 2),
            )
        if clip.fade_out_ms:
            fade_start = rect.right() - rect.width() * clip.fade_out_ms / clip.duration_ms
            painter.drawLine(
                int(fade_start),
                int(rect.top() + 2),
                int(rect.right() - 1),
                int(rect.bottom() - 2),
            )
        painter.restore()

    def _paint_clip_waveform(self, painter: QPainter, clip: StudioClip, rect: QRectF) -> None:
        asset = self._assets.get(clip.asset.asset_id)
        peaks = self._peaks.get(clip.asset.asset_id, [])
        if asset is None or not peaks or asset.duration_ms <= 0 or rect.width() < 20:
            return
        start_index = max(0, int(clip.source_start_ms / asset.duration_ms * len(peaks)))
        end_index = min(len(peaks), max(start_index + 1, int(clip.source_end_ms / asset.duration_ms * len(peaks))))
        visible = peaks[start_index:end_index]
        target_count = max(2, min(len(visible), int(rect.width() / 3)))
        if len(visible) > target_count:
            step = len(visible) / target_count
            visible = [visible[min(len(visible) - 1, int(index * step))] for index in range(target_count)]
        painter.setPen(QPen(QColor(255, 255, 255, 65 if clip.muted else 150), 1))
        center = rect.center().y() + 8
        max_height = max(2.0, rect.height() * 0.26)
        x_step = rect.width() / max(1, len(visible) - 1)
        for index, peak in enumerate(visible):
            x = rect.left() + index * x_step
            height = max(1.0, peak * max_height)
            painter.drawLine(int(x), int(center - height), int(x), int(center + height))

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._ms_to_x(self._playhead_ms)
        if x < self._header_right() or x > self.width():
            return
        painter.setPen(QPen(QColor("#e05a47"), 2))
        painter.drawLine(int(x), 0, int(x), self.height())

    def _paint_add_track_row(self, painter: QPainter) -> None:
        row = self._add_track_rect()
        background = self._theme["hover"] if self._add_track_hovered else self._theme["raised"]
        painter.fillRect(row, QColor(background))
        header_left = self._header_left()
        header_right = self._header_right()
        painter.fillRect(
            QRectF(header_left, row.top(), self.HEADER_WIDTH, row.height()),
            QColor(background),
        )
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(0, int(row.top()), self.width(), int(row.top()))
        painter.drawLine(int(header_right), int(row.top()), int(header_right), int(row.bottom()))
        painter.setPen(QColor(self._theme["text"] if self._add_track_hovered else self._theme["muted"]))
        painter.drawText(
            QRectF(header_left + 14, row.top(), self.HEADER_WIDTH - 28, row.height()),
            Qt.AlignmentFlag.AlignVCenter,
            f"+  {tr('Add Track')}",
        )
        painter.setPen(QPen(QColor(self._theme["button_border"]), 1, Qt.PenStyle.DashLine))
        center_y = int(row.center().y())
        painter.drawLine(int(header_right + 16), center_y, self.width() - 16, center_y)

    def _add_track_rect(self) -> QRectF:
        top = self._tracks_bottom()
        return QRectF(0, top, self.width(), self.ADD_TRACK_HEIGHT)

    def _clip_rect(self, clip: StudioClip, track_index: int) -> QRectF:
        left = self._ms_to_x(clip.timeline_start_ms)
        width = max(12.0, clip.duration_ms / 1000 * self._pixels_per_second)
        track = self._session.tracks[track_index]
        lane_height = self._track_height(track)
        inset = 5 if track.collapsed else 10
        top = self._track_top(track_index) + inset
        return QRectF(left, top, width, lane_height - inset * 2)

    def _clip_at(self, point: QPoint) -> tuple[StudioTrack, StudioClip, QRectF] | None:
        if self._point_in_header(point.x()):
            return None
        track = self._track_at_y(point.y())
        if track is None:
            return None
        index = self._session.tracks.index(track)
        for clip in reversed(track.clips):
            if self._clip_rect(clip, index).contains(point):
                return track, clip, self._clip_rect(clip, index)
        return None

    def _track_at_y(self, y: float) -> StudioTrack | None:
        if self._point_in_ruler(y):
            return None
        for index, track in enumerate(self._session.tracks):
            top = self._track_top(index)
            if top <= y < top + self._track_height(track):
                return track
        return None

    def _track_control_rects(self, track_index: int) -> tuple[QRectF, QRectF, QRectF]:
        top = self._track_top(track_index)
        header_left = self._header_left()
        return (
            QRectF(header_left + 12, top + 48, 28, 28),
            QRectF(header_left + 48, top + 48, 88, 28),
            QRectF(header_left + 140, top + 48, 38, 28),
        )

    def _track_title_rect(self, track: StudioTrack, track_index: int) -> QRectF:
        top = self._track_top(track_index)
        header_left = self._header_left()
        reserved_width = 98 if track.role == TRACK_AUDIO else 62
        if track.collapsed:
            return QRectF(
                header_left + 14,
                top,
                self.HEADER_WIDTH - reserved_width,
                self._track_height(track),
            )
        return QRectF(header_left + 14, top + 7, self.HEADER_WIDTH - reserved_width, 28)

    def _track_control_at(self, point: QPoint) -> tuple[StudioTrack, str, QRectF] | None:
        track = self._track_at_y(point.y())
        if track is None or not self._point_in_header(point.x()):
            return None
        index = self._session.tracks.index(track)
        collapse_rect = self._track_collapse_rect(index)
        if collapse_rect.contains(point):
            return track, "collapse", collapse_rect
        remove_rect = self._track_remove_rect(index)
        if (
            track.role == TRACK_AUDIO
            and self._hover_track_id == track.track_id
            and remove_rect.contains(point)
        ):
            return track, "remove", remove_rect
        if track.collapsed or track.role == TRACK_VIDEO:
            return None
        mute_rect, volume_rect, _value_rect = self._track_control_rects(index)
        if mute_rect.contains(point):
            return track, "mute", mute_rect
        if volume_rect.contains(point):
            return track, "volume", volume_rect
        return None

    def _track_remove_rect(self, track_index: int) -> QRectF:
        top = self._track_top(track_index)
        return QRectF(self._header_right() - 72, top + 7, 28, 28)

    def _track_collapse_rect(self, track_index: int) -> QRectF:
        top = self._track_top(track_index)
        return QRectF(self._header_right() - 40, top + 7, 28, 28)

    def _paint_track_remove_button(self, painter: QPainter, track_index: int) -> None:
        rect = self._track_remove_rect(track_index)
        palette = danger_icon_button_palette(self._theme_mode)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(palette["border"], 1))
        painter.setBrush(palette["background"])
        painter.drawRoundedRect(rect, 7, 7)
        render_app_icon(
            painter,
            rect.adjusted(6, 6, -6, -6),
            "trash",
            palette["icon"],
        )
        painter.restore()

    def _paint_track_collapse_button(
        self,
        painter: QPainter,
        track: StudioTrack,
        track_index: int,
    ) -> None:
        rect = self._track_collapse_rect(track_index)
        hovered = self._hover_control == (track.track_id, "collapse")
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self._theme["button_border"]), 1))
        painter.setBrush(QColor(self._theme["hover"] if hovered else self._theme["card"]))
        painter.drawRoundedRect(rect, 7, 7)
        render_app_icon(
            painter,
            rect.adjusted(7, 7, -7, -7),
            "chevron_down" if track.collapsed else "chevron_up",
            QColor(self._theme["text"]),
        )
        painter.restore()

    def _paint_track_controls(self, painter: QPainter, track: StudioTrack, index: int) -> None:
        if track.collapsed or track.role == TRACK_VIDEO:
            return
        mute_rect, volume_rect, value_rect = self._track_control_rects(index)
        hovered = self._hover_control
        button_background = self._theme["selection"] if track.muted else self._theme["card"]
        if hovered == (track.track_id, "mute"):
            button_background = self._theme["pressed"] if track.muted else self._theme["hover"]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self._theme["button_border"]), 1))
        painter.setBrush(QColor(button_background))
        painter.drawRoundedRect(mute_rect, 7, 7)
        render_app_icon(
            painter,
            mute_rect.adjusted(6, 6, -6, -6),
            "volume_x" if track.muted else "volume_2",
            QColor(self._theme["text"]),
        )

        rail = volume_rect.adjusted(7, 0, -7, 0)
        center_y = rail.center().y()
        display_volume = (
            self._drag_volume_value
            if (
                self._drag_mode == "volume"
                and self._drag_track_id == track.track_id
                and self._drag_volume_value is not None
            )
            else track.volume_percent
        )
        ratio = max(0.0, min(1.0, display_volume / 200))
        knob_x = rail.left() + rail.width() * ratio
        unity_x = rail.left() + rail.width() * 0.5
        painter.setPen(QPen(QColor(self._theme["button_border"]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(rail.left()), int(center_y), int(rail.right()), int(center_y))
        painter.setPen(QPen(QColor(self._theme["focus"]), 1))
        painter.drawLine(int(unity_x), int(center_y - 5), int(unity_x), int(center_y + 5))
        painter.setPen(QPen(QColor(self._theme["accent"]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(rail.left()), int(center_y), int(knob_x), int(center_y))
        painter.setPen(QPen(QColor(self._theme["surface"]), 1))
        painter.setBrush(QColor(self._theme["accent"]))
        painter.drawEllipse(QRectF(knob_x - 5, center_y - 5, 10, 10))
        painter.setPen(QColor(self._theme["muted"]))
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, f"{display_volume}%")
        painter.restore()

    def _track_volume_from_x(self, track: StudioTrack, x_position: float) -> int:
        index = self._session.tracks.index(track)
        _mute_rect, volume_rect, _value_rect = self._track_control_rects(index)
        rail = volume_rect.adjusted(7, 0, -7, 0)
        ratio = max(0.0, min(1.0, (x_position - rail.left()) / max(1.0, rail.width())))
        return round(ratio * 200)

    def _track_height(self, track: StudioTrack) -> int:
        return self.COLLAPSED_LANE_HEIGHT if track.collapsed else self.LANE_HEIGHT

    def _track_top(self, track_index: int) -> int:
        return self.RULER_HEIGHT + sum(
            self._track_height(track) for track in self._session.tracks[:track_index]
        )

    def _tracks_bottom(self) -> int:
        return self.RULER_HEIGHT + sum(
            self._track_height(track) for track in self._session.tracks
        )

    def _track_accepts_asset(self, track: StudioTrack, asset_id: str) -> bool:
        asset = self._assets.get(asset_id)
        if asset is None:
            return False
        return (track.role == TRACK_VIDEO) == (asset.media_kind == "video")

    def _track(self, track_id: str) -> StudioTrack | None:
        return next((track for track in self._session.tracks if track.track_id == track_id), None)

    def _is_first_added_track(self, track_index: int) -> bool:
        if not 0 <= track_index < len(self._session.tracks):
            return False
        if self._session.tracks[track_index].role != TRACK_AUDIO:
            return False
        return all(track.role != TRACK_AUDIO for track in self._session.tracks[:track_index])

    def _clip(self, clip_id: str) -> StudioClip | None:
        return next(
            (clip for track in self._session.tracks for clip in track.clips if clip.clip_id == clip_id),
            None,
        )

    def _track_for_clip(self, clip_id: str) -> StudioTrack | None:
        return next((track for track in self._session.tracks if any(clip.clip_id == clip_id for clip in track.clips)), None)

    def _original_clip(self) -> StudioClip:
        clip = self._clip(self._selected_clip_id)
        return clip if clip is not None else self._drag_clip

    def _ms_to_x(self, position_ms: int) -> float:
        return self.HEADER_WIDTH + max(0, position_ms) / 1000 * self._pixels_per_second

    def _x_to_ms(self, x: float) -> int:
        return max(0, round((x - self.HEADER_WIDTH) * 1000 / self._pixels_per_second))

    def _header_left(self) -> int:
        return self._horizontal_offset

    def _header_right(self) -> int:
        return self._header_left() + self.HEADER_WIDTH

    def _ruler_top(self) -> int:
        return self._vertical_offset

    def _point_in_ruler(self, y_position: float) -> bool:
        return self._ruler_top() <= y_position < self._ruler_top() + self.RULER_HEIGHT

    def _point_in_header(self, x_position: float) -> bool:
        return self._header_left() <= x_position < self._header_right()

    def _visible_duration_ms(self) -> int:
        return max(60_000, session_duration_ms(self._session) + 5_000)

    def _update_extent(self) -> None:
        width = self.HEADER_WIDTH + round(self._visible_duration_ms() / 1000 * self._pixels_per_second)
        height = self._tracks_bottom() + self.ADD_TRACK_HEIGHT
        self.setMinimumSize(max(560, width), height)
        self.resize(max(560, width), height)

    def _clear_drag(self) -> None:
        self._drag_mode = ""
        self._drag_clip = None
        self._drag_track_id = ""
        self.update()

    def _update_cursor(self, point: QPoint) -> None:
        if self._split_mode:
            hit = self._clip_at(point)
            next_hover = None
            if hit is not None:
                _track, clip, _rect = hit
                split_position = self._split_position(clip, point.x())
                if split_position is not None:
                    next_hover = (clip.clip_id, split_position)
            if next_hover != self._split_hover:
                self._split_hover = next_hover
                self.update()
            self._hover_control = None
            self._hover_track_id = ""
            self._add_track_hovered = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        effect_hit = self._effect_at(point)
        next_effect_hover = (
            (effect_hit[0].clip_id, effect_hit[1].effect_id)
            if effect_hit is not None
            else None
        )
        if next_effect_hover != self._hover_effect:
            self._hover_effect = next_effect_hover
            self.update()
        if effect_hit is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        track = self._track_at_y(point.y())
        next_hover_track_id = track.track_id if track is not None else ""
        if next_hover_track_id != self._hover_track_id:
            self._hover_track_id = next_hover_track_id
            self.update()
        add_track_hovered = self._add_track_rect().contains(point)
        if add_track_hovered != self._add_track_hovered:
            self._add_track_hovered = add_track_hovered
            self.update()
        if add_track_hovered:
            self._hover_control = None
            self._hover_track_id = ""
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        control = self._track_control_at(point)
        next_hover = (control[0].track_id, control[1]) if control is not None else None
        if next_hover != self._hover_control:
            self._hover_control = next_hover
            self.update()
        if control is not None:
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if control[1] in {"mute", "remove", "collapse"}
                else Qt.CursorShape.SizeHorCursor
            )
            return
        hit = self._clip_at(point)
        if hit is None:
            self.unsetCursor()
            return
        _track, _clip, rect = hit
        if abs(point.x() - rect.left()) <= self.HANDLE_WIDTH or abs(point.x() - rect.right()) <= self.HANDLE_WIDTH:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_control = None
        self._hover_track_id = ""
        self._add_track_hovered = False
        self._split_hover = None
        self._hover_effect = None
        self._effect_drop_clip_id = ""
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._effect_drop_clip_id = ""
        self.update()
        super().dragLeaveEvent(event)

    def _split_position(self, clip: StudioClip, x_position: float) -> int | None:
        if clip.duration_ms < 2:
            return None
        return max(
            clip.timeline_start_ms + 1,
            min(self._x_to_ms(x_position), clip.timeline_end_ms - 1),
        )

    def _request_waveforms(self) -> None:
        referenced_ids = {
            clip.asset.asset_id
            for track in self._session.tracks
            for clip in track.clips
        }
        for asset_id in referenced_ids:
            asset = self._assets.get(asset_id)
            if asset is None or asset.media_kind == "video":
                continue
            try:
                key = waveform_cache_key(asset.path, _WAVEFORM_POINTS)
            except OSError:
                continue
            cached = _WAVEFORM_CACHE.get(key)
            if cached is not None:
                self._peaks[asset.asset_id] = cached
                continue
            if key in self._pending_peak_keys:
                continue
            self._pending_peak_keys.add(key)
            future = _WAVEFORM_EXECUTOR.submit(build_waveform_peaks, asset.path, _WAVEFORM_POINTS)
            future.add_done_callback(
                lambda completed, cache_key=key, asset_id=asset.asset_id: self._emit_peaks(
                    cache_key,
                    asset_id,
                    completed,
                )
            )

    def _queue_waveform_request(self) -> None:
        self._waveform_request_timer.start()

    def _emit_peaks(self, key, asset_id: str, completed) -> None:
        try:
            peaks = completed.result()
        except Exception:
            peaks = []
        try:
            self._peaks_ready.emit((key, asset_id), peaks)
        except RuntimeError:
            pass

    def _apply_peaks(self, key_and_asset, peaks: list[float]) -> None:
        key, asset_id = key_and_asset
        self._pending_peak_keys.discard(key)
        if peaks:
            _WAVEFORM_CACHE[key] = peaks
            self._peaks[asset_id] = peaks
            self.update()


class StudioEditor(QWidget):
    session_changed = Signal(object)
    session_committed = Signal(object, bool)
    seek_requested = Signal(int)
    open_location_requested = Signal(object)
    split_mode_changed = Signal(bool)
    split_tool_available_changed = Signal(bool)
    history_availability_changed = Signal(bool, bool)

    def __init__(self, *, include_sidebars: bool = True) -> None:
        super().__init__()
        self._session = StudioSession()
        self._assets: tuple[StudioSoundAsset, ...] = ()
        self._assets_by_id: dict[str, StudioSoundAsset] = {}
        self._playhead_ms = 0
        self._split_mode = False
        self._split_tool_available = False
        self._history = SnapshotHistory[StudioSession]()
        self._history_availability = (False, False)

        self.sound_pool = StudioSoundPool(self)
        self.fx_pool = StudioFxPool(self)
        self.left_sidebar = create_workspace_splitter(
            (self.sound_pool, self.fx_pool),
            object_name="StudioLeftSidebarSplitter",
            orientation=Qt.Orientation.Vertical,
            sizes=(650, 350),
            stretch_factors=(65, 35),
            collapsible=(True, True),
        )
        self.left_sidebar.setParent(self)

        self.timeline_title = QLabel()
        self.timeline_title.setObjectName("SectionTitle")
        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        self.status_label.hide()
        timeline_header = QHBoxLayout()
        timeline_header.addWidget(self.timeline_title)
        timeline_header.addWidget(self.status_label, 1)
        timeline_header.addStretch(1)

        self.timeline = StudioTimelineView()
        self.timeline.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timeline.clip_selected.connect(self._select_clip)
        self.timeline.track_selected.connect(self._select_track)
        self.timeline.clip_moved.connect(self._move_clip)
        self.timeline.clip_trimmed.connect(self._trim_clip)
        self.timeline.asset_dropped.connect(self._drop_asset)
        self.timeline.effect_dropped.connect(self._drop_effect)
        self.timeline.effect_selected.connect(self._select_effect)
        self.timeline.effect_remove_requested.connect(self._remove_effect)
        self.timeline.track_mix_changed.connect(self._set_track_mix)
        self.timeline.track_add_requested.connect(self._add_track)
        self.timeline.track_remove_requested.connect(self._remove_track)
        self.timeline.track_collapsed_changed.connect(self._set_track_collapsed)
        self.timeline.seek_requested.connect(self._seek)
        self.timeline.clip_split_requested.connect(self._split_clip_at_position)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setObjectName("StudioTimelineScroll")
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(
            self.timeline.set_horizontal_offset
        )
        self.timeline_scroll.verticalScrollBar().valueChanged.connect(
            self.timeline.set_vertical_offset
        )

        self.timeline_panel = QFrame(self)
        self.timeline_panel.setObjectName("Card")
        timeline_layout = QVBoxLayout(self.timeline_panel)
        timeline_layout.setContentsMargins(14, 14, 14, 14)
        timeline_layout.setSpacing(10)
        timeline_layout.addLayout(timeline_header)
        timeline_layout.addWidget(self.timeline_scroll, 1)

        self.inspector = StudioInspector(self)
        self.inspector.clip_values_changed.connect(self._set_clip_values)
        self.inspector.track_mix_changed.connect(self._set_track_mix)
        self.inspector.track_name_changed.connect(self._set_track_name)
        self.inspector.effect_changed.connect(self._update_effect)
        self.inspector.effect_remove_requested.connect(self._remove_effect)
        self.inspector.open_location_requested.connect(self.open_location_requested.emit)
        self.inspector_scroll = QScrollArea(self)
        self.inspector_scroll.setObjectName("StudioInspectorScroll")
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.inspector_scroll.setMinimumWidth(280)
        self.inspector_scroll.setMaximumWidth(460)
        self.inspector_scroll.setWidget(self.inspector)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.workspace_splitter: QSplitter | None = None
        if include_sidebars:
            self.workspace_splitter = create_workspace_splitter(
                (self.left_sidebar, self.timeline_panel, self.inspector_scroll),
                object_name="StudioEditorSplitter",
                sizes=(310, 900, 280),
                stretch_factors=(0, 1, 0),
                collapsible=(True, False, True),
            )
            layout.addWidget(self.workspace_splitter, 1)
        else:
            layout.addWidget(self.timeline_panel, 1)
        self._clip_delete_shortcuts = tuple(
            self._create_clip_delete_shortcut(key)
            for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        )
        self.apply_language()

    def _create_clip_delete_shortcut(self, key: Qt.Key) -> QShortcut:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._remove_selected_clip)
        return shortcut

    def set_context(
        self,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...],
    ) -> None:
        self._session = session
        self._assets = assets
        self._assets_by_id = {asset.asset_id: asset for asset in assets}
        self.sound_pool.set_assets(assets)
        self.timeline.set_context(session, assets)
        self._sync_inspector()
        self._update_split_tool_availability()
        self._history = SnapshotHistory()
        self._update_history_availability()

    def session(self) -> StudioSession:
        return self._session

    def set_playhead(self, position_ms: int) -> None:
        self._playhead_ms = max(0, int(position_ms))
        self.timeline.set_playhead(self._playhead_ms)

    def set_split_mode(self, enabled: bool) -> None:
        next_mode = bool(enabled) and self._split_tool_available
        if next_mode == self._split_mode:
            self.timeline.set_split_mode(next_mode)
            return
        self._split_mode = next_mode
        self.timeline.set_split_mode(next_mode)
        self.split_mode_changed.emit(next_mode)

    def _split_clip_at_position(self, clip_id: str, position_ms: int) -> None:
        try:
            updated = split_studio_clip(
                self._session,
                clip_id,
                timeline_position_ms=position_ms,
            )
        except StudioTimelineError as exc:
            self.set_status(str(exc))
            return
        self._seek(position_ms)
        self._commit(updated)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_theme_mode(self, theme_mode: str) -> None:
        self.sound_pool.set_theme_mode(theme_mode)
        self.fx_pool.set_theme_mode(theme_mode)
        self.timeline.set_theme_mode(theme_mode)
        self.inspector.set_theme_mode(theme_mode)

    def set_zoom(self, value: int) -> None:
        self.timeline.set_zoom(value)

    def apply_language(self) -> None:
        self.timeline_title.setText(tr("Timeline"))
        self.sound_pool.apply_language()
        self.fx_pool.apply_language()
        self.inspector.apply_language()

    def _seek(self, position_ms: int) -> None:
        self.set_playhead(position_ms)
        self.seek_requested.emit(position_ms)

    def _drop_asset(self, asset_id: str, track_id: str, position_ms: int) -> None:
        asset = self._assets_by_id.get(asset_id)
        if asset is None or asset.duration_ms <= 0:
            self.set_status(tr("The sound duration could not be read."))
            return
        target = next((track for track in self._session.tracks if track.track_id == track_id), None)
        if target is None or (target.role == TRACK_VIDEO) != (asset.media_kind == "video"):
            self.set_status(tr("Video can only be placed on the video track."))
            return
        try:
            self._commit(self._add_clip(track_id, asset, position_ms))
        except StudioTimelineError as exc:
            self.set_status(str(exc))

    def _drop_effect(self, effect_kind: str, clip_id: str) -> None:
        if effect_kind != "reverb" or self._clip(clip_id) is None:
            return
        effect = StudioEffect(
            effect_id=f"fx-{uuid.uuid4().hex}",
            kind=effect_kind,
        )
        try:
            self._commit(add_studio_clip_effect(self._session, clip_id, effect))
            self.timeline.select_clip(clip_id)
        except StudioTimelineError as exc:
            self.set_status(str(exc))

    def _update_effect(self, clip_id: str, effect: StudioEffect) -> None:
        try:
            self._commit(update_studio_clip_effect(self._session, clip_id, effect))
            self.timeline.select_clip(clip_id)
        except StudioTimelineError as exc:
            self.set_status(str(exc))

    def _remove_effect(self, clip_id: str, effect_id: str) -> None:
        try:
            self._commit(remove_studio_clip_effect(self._session, clip_id, effect_id))
            self.timeline.select_clip(clip_id)
        except StudioTimelineError as exc:
            self.set_status(str(exc))

    def _add_clip(
        self,
        track_id: str,
        asset: StudioSoundAsset,
        position_ms: int,
    ) -> StudioSession:
        return add_studio_clip(
            self._session,
            track_id,
            asset.reference,
            asset.duration_ms,
            timeline_start_ms=position_ms,
        )

    def _add_track(self) -> None:
        updated = add_studio_track(self._session)
        track_id = updated.tracks[-1].track_id
        self._commit(updated)
        self.timeline.select_track(track_id)

    def _remove_track(self, track_id: str) -> None:
        self._commit(remove_studio_track(self._session, track_id))

    def _set_track_collapsed(self, track_id: str, collapsed: bool) -> None:
        self._commit(set_studio_track_collapsed(self._session, track_id, collapsed))

    def _move_clip(self, clip_id: str, track_id: str, position_ms: int) -> None:
        try:
            self._commit(
                move_studio_clip(
                    self._session,
                    clip_id,
                    track_id=track_id,
                    timeline_start_ms=position_ms,
                )
            )
        except StudioTimelineError as exc:
            self.set_status(str(exc))

    def _trim_clip(self, clip_id: str, start_ms: int, end_ms: int, preserve_end: bool) -> None:
        self._commit(
            trim_studio_clip(
                self._session,
                clip_id,
                source_start_ms=start_ms,
                source_end_ms=end_ms,
                preserve_timeline_end=preserve_end,
            )
        )

    def _set_clip_values(
        self,
        clip_id: str,
        position_ms: int,
        source_start_ms: int,
        source_end_ms: int,
        gain_db: float,
        muted: bool | None = None,
        fade_in_ms: int | None = None,
        fade_out_ms: int | None = None,
    ) -> None:
        track = self._track_for_clip(clip_id)
        if track is None:
            return
        current_clip = self._clip(clip_id)
        if current_clip is None:
            return
        try:
            updated = trim_studio_clip(
                self._session,
                clip_id,
                source_start_ms=source_start_ms,
                source_end_ms=source_end_ms,
            )
            updated = move_studio_clip(
                updated,
                clip_id,
                track_id=track.track_id,
                timeline_start_ms=position_ms,
            )
            updated = set_studio_clip_mix(
                updated,
                clip_id,
                gain_db=gain_db,
                muted=current_clip.muted if muted is None else muted,
                fade_in_ms=current_clip.fade_in_ms if fade_in_ms is None else fade_in_ms,
                fade_out_ms=current_clip.fade_out_ms if fade_out_ms is None else fade_out_ms,
            )
            self._commit(updated)
        except StudioTimelineError as exc:
            self.set_status(str(exc))
            self._sync_inspector(clip_id=clip_id)

    def _remove_clip(self, clip_id: str) -> None:
        self._commit(remove_studio_clip(self._session, clip_id))

    def _remove_selected_clip(self) -> None:
        if isinstance(
            QApplication.focusWidget(),
            (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit),
        ):
            return
        clip_id = self.timeline.selected_clip_id()
        if clip_id:
            self._remove_clip(clip_id)

    def _set_track_mix(
        self,
        track_id: str,
        muted: bool,
        solo: bool,
        volume: int,
        pan: int | None = None,
    ) -> None:
        self._commit(
            set_studio_track_mix(
                self._session,
                track_id,
                muted=muted,
                solo=solo,
                volume_percent=volume,
                pan_percent=pan,
            )
        )

    def _set_track_name(self, track_id: str, name: str) -> None:
        self._commit(set_studio_track_name(self._session, track_id, name))

    def _select_clip(self, clip_id: str) -> None:
        self._sync_inspector(clip_id=clip_id)

    def _select_effect(self, clip_id: str, effect_id: str) -> None:
        self._sync_inspector(clip_id=clip_id)
        self.inspector.open_effect_tab(effect_id)

    def _select_track(self, track_id: str) -> None:
        self._sync_inspector(track_id=track_id)

    def undo(self) -> bool:
        target, history = self._history.undo(self._session)
        if target is None:
            return False
        self._history = history
        self._apply_committed_session(target)
        return True

    def redo(self) -> bool:
        target, history = self._history.redo(self._session)
        if target is None:
            return False
        self._history = history
        self._apply_committed_session(target)
        return True

    def _commit(self, session: StudioSession) -> None:
        if session == self._session:
            return
        self._history = self._history.record(self._session)
        self._apply_committed_session(session)

    def _apply_committed_session(self, session: StudioSession) -> None:
        requires_render = _playback_layout_signature(self._session) != _playback_layout_signature(
            session
        )
        self._session = session
        self.set_status("")
        if requires_render:
            self.timeline.set_context(session, self._assets)
        else:
            self.timeline.update_session(session)
        self._sync_inspector(clip_id=self.timeline.selected_clip_id(), track_id=self.timeline.selected_track_id())
        self._update_split_tool_availability()
        self._update_history_availability()
        self.session_changed.emit(session)
        self.session_committed.emit(session, requires_render)

    def _update_history_availability(self) -> None:
        availability = (self._history.can_undo, self._history.can_redo)
        if availability == self._history_availability:
            return
        self._history_availability = availability
        self.history_availability_changed.emit(*availability)

    def _update_split_tool_availability(self) -> None:
        available = any(
            clip.duration_ms >= 2
            for track in self._session.tracks
            for clip in track.clips
        )
        if not available and self._split_mode:
            self.set_split_mode(False)
        if available == self._split_tool_available:
            return
        self._split_tool_available = available
        self.split_tool_available_changed.emit(available)

    def _sync_inspector(self, *, clip_id: str = "", track_id: str = "") -> None:
        clip = self._clip(clip_id) if clip_id else None
        track = self._track_for_clip(clip.clip_id) if clip is not None else self._track(track_id)
        asset = self._assets_by_id.get(clip.asset.asset_id) if clip is not None else None
        self.inspector.set_selection(track, clip, asset)

    def _clip(self, clip_id: str) -> StudioClip | None:
        return next(
            (clip for track in self._session.tracks for clip in track.clips if clip.clip_id == clip_id),
            None,
        )

    def _track(self, track_id: str) -> StudioTrack | None:
        return next((track for track in self._session.tracks if track.track_id == track_id), None)

    def _track_for_clip(self, clip_id: str) -> StudioTrack | None:
        return next(
            (track for track in self._session.tracks if any(clip.clip_id == clip_id for clip in track.clips)),
            None,
        )


def _playback_layout_signature(session: StudioSession) -> tuple[object, ...]:
    return tuple(
        (
            track.track_id,
            track.role,
            track.pan_percent,
            tuple(
                (
                    clip.clip_id,
                    clip.asset,
                    clip.timeline_start_ms,
                    clip.source_start_ms,
                    clip.source_end_ms,
                    clip.fade_in_ms,
                    clip.fade_out_ms,
                )
                for clip in track.clips
            ),
        )
        for track in session.tracks
    )


def _format_time(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"
