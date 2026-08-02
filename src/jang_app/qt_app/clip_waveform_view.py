from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from jang_app.services.model_dataset import ModelDatasetClip
from jang_app.services.silence_detection import SpeechRegion
from jang_app.services.waveform import build_waveform_peaks, waveform_cache_key


_WAVEFORM_POINT_COUNT = 2400
_WAVEFORM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-waveform")
_WAVEFORM_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
atexit.register(lambda: _WAVEFORM_EXECUTOR.shutdown(wait=False, cancel_futures=True))


class ClipWaveformView(QWidget):
    _peaks_ready = Signal(object, object)
    selection_changed = Signal(int, int)
    clip_preview_changed = Signal(int, int)
    clip_edit_finished = Signal(str, int, int)
    clip_selected = Signal(str)
    seek_requested = Signal(int)
    zoom_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DatasetEditorWaveform")
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._theme_mode = "white"
        self._peaks: list[float] = []
        self._waveform_key: tuple[str, int, int, int] | None = None
        self._duration_ms = 0
        self._clips: tuple[ModelDatasetClip, ...] = ()
        self._suggestions: tuple[tuple[SpeechRegion, bool], ...] = ()
        self._selection_start_ms = 0
        self._selection_end_ms = 0
        self._playhead_ms = 0
        self._zoom = 1
        self._view_center_ms = 0
        self._selected_clip_id = ""
        self._edit_start_ms = 0
        self._edit_end_ms = 0
        self._press_x = 0.0
        self._selection_anchor_ms = 0
        self._selecting = False
        self._panning = False
        self._pan_center_ms = 0
        self._pressed_clip_id = ""
        self._drag_handle = ""
        self._drag_original_range = (0, 0)
        self._peaks_ready.connect(self._apply_peaks)

    @property
    def selected_clip_id(self) -> str:
        return self._selected_clip_id

    def set_audio(self, path: Path | None, duration_ms: int, clips: tuple[ModelDatasetClip, ...]) -> None:
        self._duration_ms = max(0, duration_ms)
        self._clips = clips
        self._suggestions = ()
        self._selection_start_ms = 0
        self._selection_end_ms = self._duration_ms
        self._playhead_ms = 0
        self._zoom = 1
        self._view_center_ms = self._duration_ms // 2
        self._selected_clip_id = ""
        self._edit_start_ms = 0
        self._edit_end_ms = 0
        self._load_waveform(path)
        self.update()

    def _load_waveform(self, path: Path | None) -> None:
        if path is None:
            self._waveform_key = None
            self._peaks = []
            return
        try:
            cache_key = waveform_cache_key(path, _WAVEFORM_POINT_COUNT)
        except OSError:
            self._waveform_key = None
            self._peaks = []
            return
        if cache_key == self._waveform_key:
            return
        self._waveform_key = cache_key
        cached = _WAVEFORM_CACHE.get(cache_key)
        if cached is not None:
            self._peaks = cached
            return
        self._peaks = []
        future = _WAVEFORM_EXECUTOR.submit(build_waveform_peaks, path, _WAVEFORM_POINT_COUNT)
        future.add_done_callback(lambda completed, key=cache_key: self._emit_peaks(key, completed))

    def _emit_peaks(self, cache_key: tuple[str, int, int, int], completed) -> None:
        try:
            peaks = completed.result()
        except Exception:
            peaks = []
        self._peaks_ready.emit(cache_key, peaks)

    def _apply_peaks(self, cache_key: tuple[str, int, int, int], peaks: list[float]) -> None:
        _WAVEFORM_CACHE[cache_key] = peaks
        if cache_key == self._waveform_key:
            self._peaks = peaks
            self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_selection(self, start_ms: int, end_ms: int) -> None:
        self._selection_start_ms = max(0, min(start_ms, self._duration_ms))
        self._selection_end_ms = max(self._selection_start_ms, min(end_ms, self._duration_ms))
        if not self._selected_clip_id:
            self._edit_start_ms = self._selection_start_ms
            self._edit_end_ms = self._selection_end_ms
        self.update()

    def select_clip(self, clip_id: str) -> tuple[int, int] | None:
        clip = self._clip_by_id(clip_id)
        if clip is None:
            self.clear_clip_selection()
            return None
        self._selected_clip_id = clip.clip_id
        self._edit_start_ms = clip.start_ms
        self._edit_end_ms = clip.end_ms
        self.set_selection(clip.start_ms, clip.end_ms)
        return (clip.start_ms, clip.end_ms)

    def clear_clip_selection(self) -> None:
        self._selected_clip_id = ""
        self._drag_handle = ""
        self.update()

    def set_playhead(self, position_ms: int) -> None:
        self._playhead_ms = max(0, min(position_ms, self._duration_ms))
        self.update()

    def set_suggestions(self, suggestions: tuple[tuple[SpeechRegion, bool], ...]) -> None:
        self._suggestions = suggestions
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self._zoom = max(1, min(12, zoom))
        self._view_center_ms = self._clamp_center(self._playhead_ms or self._view_center_ms)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        colors = _waveform_palette(self._theme_mode)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(QBrush(colors["background"]))
        painter.drawRoundedRect(outer, 10, 10)
        content = self._content_rect()
        painter.setPen(QPen(colors["midline"], 1))
        painter.drawLine(QPointF(content.left(), content.center().y()), QPointF(content.right(), content.center().y()))

        visible_start, visible_end = self._visible_range()
        self._paint_suggestions(painter, content, colors)
        self._paint_clips(painter, content, colors)
        self._paint_peaks(painter, content, visible_start, visible_end, colors["wave"])
        self._paint_selection(painter, content, colors)
        self._paint_playhead(painter, content, colors)
        self._paint_times(painter, content, outer, visible_start, visible_end, colors["text"])

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._duration_ms <= 0:
            return
        self._press_x = event.position().x()
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._handle_at(event.position().x(), event.position().y())
            if handle:
                self._drag_handle = handle
                if not self._selected_clip_id:
                    self._edit_start_ms = self._selection_start_ms
                    self._edit_end_ms = self._selection_end_ms
                self._drag_original_range = (self._edit_start_ms, self._edit_end_ms)
                event.accept()
                return
            self._selection_anchor_ms = self._x_to_ms(self._press_x)
            self._pressed_clip_id = self._clip_id_at(self._selection_anchor_ms)
            self._selecting = False
            event.accept()
            return
        if event.button() in {Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton}:
            self._panning = True
            self._pan_center_ms = self._view_center_ms
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_handle and event.buttons() & Qt.MouseButton.LeftButton:
            self._move_handle(self._x_to_ms(event.position().x()))
            event.accept()
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            if abs(event.position().x() - self._press_x) >= 3:
                if not self._selecting:
                    self._selecting = True
                    self.clear_clip_selection()
                    self.clip_selected.emit("")
                current_ms = self._x_to_ms(event.position().x())
                start = min(self._selection_anchor_ms, current_ms)
                end = max(self._selection_anchor_ms, current_ms)
                self.set_selection(start, end)
                self.selection_changed.emit(self._selection_start_ms, self._selection_end_ms)
            event.accept()
            return
        if self._panning and event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
            content_width = max(1.0, self._content_rect().width())
            visible_duration = self._visible_range()[1] - self._visible_range()[0]
            delta_ms = round((self._press_x - event.position().x()) / content_width * visible_duration)
            self._view_center_ms = self._clamp_center(self._pan_center_ms + delta_ms)
            self.update()
            event.accept()
            return
        self._update_cursor(event.position().x(), event.position().y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle:
            self._finish_handle_drag()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._selecting:
                position_ms = self._x_to_ms(event.position().x())
                if self._pressed_clip_id:
                    self.select_clip(self._pressed_clip_id)
                    self.clip_selected.emit(self._pressed_clip_id)
                self.set_playhead(position_ms)
                self.seek_requested.emit(position_ms)
            self._pressed_clip_id = ""
            self._selecting = False
            event.accept()
            return
        if event.button() in {Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton}:
            self._panning = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        step = 1 if event.angleDelta().y() > 0 else -1
        zoom = max(1, min(12, self._zoom + step))
        if zoom != self._zoom:
            self.zoom_changed.emit(zoom)
        event.accept()

    def _move_handle(self, position_ms: int) -> None:
        if self._drag_handle == "start":
            self._edit_start_ms = max(0, min(position_ms, self._edit_end_ms - 100))
        else:
            self._edit_end_ms = min(self._duration_ms, max(position_ms, self._edit_start_ms + 100))
        self._selection_start_ms = self._edit_start_ms
        self._selection_end_ms = self._edit_end_ms
        if self._selected_clip_id:
            self.clip_preview_changed.emit(self._edit_start_ms, self._edit_end_ms)
        else:
            self.selection_changed.emit(self._edit_start_ms, self._edit_end_ms)
        self.update()

    def _finish_handle_drag(self) -> None:
        clip_id = self._selected_clip_id
        changed = self._drag_original_range != (self._edit_start_ms, self._edit_end_ms)
        self._drag_handle = ""
        self.unsetCursor()
        if clip_id and changed:
            self.clip_edit_finished.emit(clip_id, self._edit_start_ms, self._edit_end_ms)

    def _paint_suggestions(self, painter: QPainter, content: QRectF, colors: dict[str, QColor]) -> None:
        for region, is_enabled in self._suggestions:
            left = self._ms_to_x(region.start_ms)
            right = self._ms_to_x(region.end_ms)
            region_rect = QRectF(left, content.top(), max(1.0, right - left), content.height())
            color = colors["suggestion"] if is_enabled else colors["suggestion_disabled"]
            painter.fillRect(region_rect.intersected(content), color)

    def _paint_clips(self, painter: QPainter, content: QRectF, colors: dict[str, QColor]) -> None:
        for clip in self._clips:
            is_selected = clip.clip_id == self._selected_clip_id
            start = self._edit_start_ms if is_selected else clip.start_ms
            end = self._edit_end_ms if is_selected else clip.end_ms
            left = self._ms_to_x(start)
            right = self._ms_to_x(end)
            clip_rect = QRectF(left, content.top(), max(1.0, right - left), content.height())
            painter.fillRect(clip_rect.intersected(content), colors["selected_clip" if is_selected else "clip"])
        if self._selected_clip_id:
            self._paint_handles(painter, content, colors, self._edit_start_ms, self._edit_end_ms)

    def _paint_handles(
        self,
        painter: QPainter,
        content: QRectF,
        colors: dict[str, QColor],
        start_ms: int,
        end_ms: int,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(colors["handle"], 2))
        painter.setBrush(QBrush(colors["handle"]))
        for position_ms in (start_ms, end_ms):
            x_position = self._ms_to_x(position_ms)
            painter.drawLine(QPointF(x_position, content.top()), QPointF(x_position, content.bottom()))
            grip = QRectF(x_position - 4, content.center().y() - 13, 8, 26)
            painter.drawRoundedRect(grip, 4, 4)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _paint_selection(self, painter: QPainter, content: QRectF, colors: dict[str, QColor]) -> None:
        left = self._ms_to_x(self._selection_start_ms)
        right = self._ms_to_x(self._selection_end_ms)
        selection_rect = QRectF(left, content.top(), max(1.0, right - left), content.height())
        painter.fillRect(selection_rect.intersected(content), colors["selection"])
        if not self._selected_clip_id:
            painter.setPen(QPen(colors["selection_edge"], 2))
            painter.drawLine(QPointF(left, content.top()), QPointF(left, content.bottom()))
            painter.drawLine(QPointF(right, content.top()), QPointF(right, content.bottom()))
            if self._selection_end_ms - self._selection_start_ms >= 100:
                self._paint_handles(
                    painter,
                    content,
                    colors,
                    self._selection_start_ms,
                    self._selection_end_ms,
                )

    def _paint_playhead(self, painter: QPainter, content: QRectF, colors: dict[str, QColor]) -> None:
        playhead_x = self._ms_to_x(self._playhead_ms)
        painter.setPen(QPen(colors["playhead"], 2))
        painter.drawLine(QPointF(playhead_x, content.top()), QPointF(playhead_x, content.bottom()))

    def _paint_times(
        self,
        painter: QPainter,
        content: QRectF,
        outer: QRectF,
        visible_start: int,
        visible_end: int,
        color: QColor,
    ) -> None:
        painter.setPen(QPen(color, 1))
        left_rect = QRectF(content.left(), outer.bottom() - 22, 90, 18)
        right_rect = QRectF(content.right() - 90, outer.bottom() - 22, 90, 18)
        painter.drawText(left_rect, Qt.AlignmentFlag.AlignLeft, _format_time(visible_start))
        painter.drawText(right_rect, Qt.AlignmentFlag.AlignRight, _format_time(visible_end))

    def _paint_peaks(
        self,
        painter: QPainter,
        content: QRectF,
        visible_start: int,
        visible_end: int,
        color: QColor,
    ) -> None:
        if not self._peaks or self._duration_ms <= 0:
            return
        start_index = max(0, int(visible_start / self._duration_ms * len(self._peaks)))
        calculated_end = int(visible_end / self._duration_ms * len(self._peaks)) + 1
        end_index = min(len(self._peaks), max(start_index + 1, calculated_end))
        visible_peaks = self._peaks[start_index:end_index]
        painter.setPen(QPen(color, 1))
        step = content.width() / max(1, len(visible_peaks) - 1)
        center_y = content.center().y()
        max_height = content.height() * 0.44
        for index, peak in enumerate(visible_peaks):
            x_position = content.left() + index * step
            height = max(1.0, peak * max_height)
            painter.drawLine(QPointF(x_position, center_y - height), QPointF(x_position, center_y + height))

    def _handle_at(self, x_position: float, y_position: float) -> str:
        if not self._content_rect().contains(QPointF(x_position, y_position)):
            return ""
        start_ms = self._edit_start_ms if self._selected_clip_id else self._selection_start_ms
        end_ms = self._edit_end_ms if self._selected_clip_id else self._selection_end_ms
        if end_ms - start_ms < 100:
            return ""
        if abs(x_position - self._ms_to_x(start_ms)) <= 8:
            return "start"
        if abs(x_position - self._ms_to_x(end_ms)) <= 8:
            return "end"
        return ""

    def _update_cursor(self, x_position: float, y_position: float) -> None:
        cursor = (
            Qt.CursorShape.SizeHorCursor
            if self._handle_at(x_position, y_position)
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)

    def _clip_by_id(self, clip_id: str) -> ModelDatasetClip | None:
        return next((clip for clip in self._clips if clip.clip_id == clip_id), None)

    def _clip_id_at(self, position_ms: int) -> str:
        candidates = [clip for clip in self._clips if clip.start_ms <= position_ms <= clip.end_ms]
        return min(candidates, key=lambda clip: clip.duration_ms).clip_id if candidates else ""

    def _content_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(14, 10, -14, -26)

    def _visible_range(self) -> tuple[int, int]:
        if self._duration_ms <= 0:
            return (0, 0)
        visible_duration = max(1, round(self._duration_ms / self._zoom))
        center = self._clamp_center(self._view_center_ms)
        start = max(0, min(self._duration_ms - visible_duration, center - visible_duration // 2))
        return (start, min(self._duration_ms, start + visible_duration))

    def _clamp_center(self, center_ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        half = max(1, round(self._duration_ms / self._zoom)) // 2
        if self._duration_ms <= half * 2:
            return self._duration_ms // 2
        return max(half, min(self._duration_ms - half, center_ms))

    def _x_to_ms(self, x_position: float) -> int:
        content = self._content_rect()
        ratio = max(0.0, min(1.0, (x_position - content.left()) / max(1.0, content.width())))
        start, end = self._visible_range()
        return round(start + ratio * (end - start))

    def _ms_to_x(self, position_ms: int) -> float:
        content = self._content_rect()
        start, end = self._visible_range()
        ratio = (position_ms - start) / max(1, end - start)
        return content.left() + max(0.0, min(1.0, ratio)) * content.width()


def _format_time(milliseconds: int) -> str:
    total_tenths = max(0, milliseconds) // 100
    minutes, tenths = divmod(total_tenths, 600)
    seconds, tenth = divmod(tenths, 10)
    return f"{minutes:02d}:{seconds:02d}.{tenth}"


def _waveform_palette(theme_mode: str) -> dict[str, QColor]:
    if theme_mode == "dark":
        return {
            "background": QColor("#191919"),
            "border": QColor("#383835"),
            "midline": QColor("#55544f"),
            "wave": QColor("#deddd8"),
            "selection": QColor(236, 235, 231, 45),
            "selection_edge": QColor("#ecebe7"),
            "clip": QColor(236, 235, 231, 22),
            "selected_clip": QColor(236, 235, 231, 58),
            "suggestion": QColor(85, 145, 104, 65),
            "suggestion_disabled": QColor(137, 135, 128, 25),
            "handle": QColor("#c93d3d"),
            "playhead": QColor("#c93d3d"),
            "text": QColor("#898780"),
        }
    return {
        "background": QColor("#fffdf7"),
        "border": QColor("#d8d0c2"),
        "midline": QColor("#c2baad"),
        "wave": QColor("#10100e"),
        "selection": QColor(16, 16, 14, 30),
        "selection_edge": QColor("#10100e"),
        "clip": QColor(16, 16, 14, 16),
        "selected_clip": QColor(16, 16, 14, 42),
        "suggestion": QColor(55, 125, 78, 55),
        "suggestion_disabled": QColor(110, 106, 97, 20),
        "handle": QColor("#c93d3d"),
        "playhead": QColor("#c93d3d"),
        "text": QColor("#6e6a61"),
    }
