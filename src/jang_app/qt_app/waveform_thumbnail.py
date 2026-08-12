from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy

from jang_app.services.waveform import build_waveform_peaks, waveform_cache_key


_WAVEFORM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail-waveform")
_WAVEFORM_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
atexit.register(lambda: _WAVEFORM_EXECUTOR.shutdown(wait=False, cancel_futures=True))


class WaveformThumbnail(QFrame):
    _peaks_ready = Signal(object, object)

    def __init__(
        self,
        *,
        point_count: int = 160,
        height: int = 42,
        minimum_width: int = 0,
    ) -> None:
        super().__init__()
        self.setObjectName("MiniWaveform")
        self.setFixedHeight(max(24, int(height)))
        self.setMinimumWidth(max(0, int(minimum_width)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._point_count = max(24, int(point_count))
        self._peaks: list[float] = []
        self._theme_mode = "white"
        self._is_available = False
        self._is_loading = False
        self._did_attempt_load = False
        self._cache_key: tuple[str, int, int, int] | None = None
        self._path: Path | None = None
        self._peaks_ready.connect(self._apply_peaks)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def set_path(self, path: Path | None) -> None:
        self._peaks = []
        self._is_available = False
        self._is_loading = False
        self._did_attempt_load = False
        self._cache_key = None
        self._path = path
        if path is None:
            self.update()
            return
        try:
            cache_key = waveform_cache_key(path, self._point_count)
        except Exception:
            self.update()
            return
        cached = _WAVEFORM_CACHE.get(cache_key)
        if cached is not None:
            self._peaks = cached
            self._is_available = bool(cached)
            self._did_attempt_load = True
        self._cache_key = cache_key
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        colors = _waveform_palette(self._theme_mode)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colors["background"]))
        painter.drawRoundedRect(rect, 9, 9)
        content = rect.adjusted(10, 7, -10, -7)
        center_y = content.center().y()
        painter.setPen(QPen(colors["midline"], 1))
        painter.drawLine(QPointF(content.left(), center_y), QPointF(content.right(), center_y))
        if not self._is_available:
            self._ensure_loading()
            _draw_placeholder(painter, content, colors["muted"])
            return
        painter.setPen(QPen(colors["wave"], 1))
        step = content.width() / max(1, len(self._peaks) - 1)
        max_height = content.height() * 0.46
        for index, peak in enumerate(self._peaks):
            x = content.left() + index * step
            amplitude = max(1.0, peak * max_height)
            painter.drawLine(QPointF(x, center_y - amplitude), QPointF(x, center_y + amplitude))

    def _ensure_loading(self) -> None:
        if self._path is None or self._is_loading or self._is_available or self._did_attempt_load:
            return
        if self._cache_key is None:
            return
        self._is_loading = True
        self._did_attempt_load = True
        future = _WAVEFORM_EXECUTOR.submit(
            build_waveform_peaks,
            self._path,
            self._point_count,
        )
        future.add_done_callback(
            lambda completed, key=self._cache_key: self._emit_peaks(key, completed)
        )

    def _emit_peaks(self, cache_key: tuple[str, int, int, int], completed) -> None:
        try:
            peaks = completed.result()
        except Exception:
            peaks = []
        try:
            self._peaks_ready.emit(cache_key, peaks)
        except RuntimeError:
            pass

    def _apply_peaks(self, cache_key: tuple[str, int, int, int], peaks: list[float]) -> None:
        if cache_key != self._cache_key:
            return
        if peaks:
            _WAVEFORM_CACHE[cache_key] = peaks
        else:
            _WAVEFORM_CACHE.pop(cache_key, None)
        self._peaks = peaks
        self._is_available = bool(peaks)
        self._is_loading = False
        self._did_attempt_load = True
        self.update()


def _waveform_palette(theme_mode: str) -> dict[str, QColor]:
    if theme_mode == "dark":
        return {
            "background": QColor("#202020"),
            "midline": QColor("#55544f"),
            "wave": QColor("#deddd8"),
            "muted": QColor("#898780"),
        }
    return {
        "background": QColor("#ebe7dd"),
        "midline": QColor("#c8c0b2"),
        "wave": QColor("#10100e"),
        "muted": QColor("#8b857a"),
    }


def _draw_placeholder(painter: QPainter, content: QRectF, color: QColor) -> None:
    painter.setPen(QPen(color, 1))
    center_y = content.center().y()
    step = max(6.0, content.width() / 24)
    max_height = content.height() * 0.28
    x = content.left()
    index = 0
    while x <= content.right():
        amplitude = max_height * (0.25 + 0.75 * ((index % 5) / 4))
        painter.drawLine(QPointF(x, center_y - amplitude), QPointF(x, center_y + amplitude))
        x += step
        index += 1
