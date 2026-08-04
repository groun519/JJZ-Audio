from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTitleLabel
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.song_metadata import SongDisplayMetadata
from jang_app.services.waveform import build_waveform_peaks, waveform_cache_key


_WAVEFORM_POINT_COUNT = 160
_WAVEFORM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="library-waveform")
_WAVEFORM_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
atexit.register(lambda: _WAVEFORM_EXECUTOR.shutdown(wait=False, cancel_futures=True))


class SongListRow(QWidget):
    rename_requested = Signal(str, str)
    remove_requested = Signal(str)
    use_requested = Signal(str)
    details_requested = Signal(str)
    preview_requested = Signal(str)
    preview_play_toggled = Signal(str)
    preview_seek_requested = Signal(str, int)
    preview_height_changed = Signal(str)

    def __init__(self, item_id: str, title: str, metadata: SongDisplayMetadata) -> None:
        super().__init__()
        self.setObjectName("SongListRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self._item_id = item_id
        self._is_editing = False
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

        self.waveform = MiniWaveformView()
        self.waveform.set_path(metadata.waveform_path)

        self.use_button = SvgIconButton("arrow_right", size=30)
        set_translated_tooltip(self.use_button, "Open in Vocal")
        self.use_button.clicked.connect(lambda: self.use_requested.emit(self._item_id))
        self.details_button = SvgIconButton("database", size=30)
        set_translated_tooltip(self.details_button, "Open song details")
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self._item_id))
        self.rename_button = SvgIconButton("edit", size=30)
        set_translated_tooltip(self.rename_button, "Rename")
        self.rename_button.clicked.connect(self._begin_rename)
        self.remove_button = SvgIconButton("trash", size=30)
        set_translated_tooltip(self.remove_button, "Remove")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self._item_id))
        self.action_buttons = (
            self.use_button,
            self.details_button,
            self.rename_button,
            self.remove_button,
        )

        action_container = QWidget()
        action_container.setObjectName("SongActionSlot")
        action_container.setFixedWidth(141)
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(7)
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

        self._set_actions_visible(False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 138 if self._preview_expanded else 84)

    def set_theme_mode(self, theme_mode: str) -> None:
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

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._is_editing:
            self._set_actions_visible(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self._is_editing:
            self.preview_requested.emit(self._item_id)
        super().mouseReleaseEvent(event)

    def _set_actions_visible(self, is_visible: bool) -> None:
        for button in self.action_buttons:
            button.setVisible(is_visible)

    def _begin_rename(self) -> None:
        self._is_editing = True
        self.title_edit.setText(self.title_label.text())
        self.title_label.hide()
        self.title_edit.show()
        self._set_actions_visible(True)
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
        if next_title and next_title != current_title:
            self.rename_requested.emit(self._item_id, next_title)
        else:
            self.title_edit.setText(current_title)


class MiniWaveformView(QFrame):
    _peaks_ready = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("MiniWaveform")
        self.setFixedHeight(42)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
            cache_key = waveform_cache_key(path, _WAVEFORM_POINT_COUNT)
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

    def _emit_peaks(self, cache_key: tuple[str, int, int, int], completed) -> None:
        try:
            peaks = completed.result()
        except Exception:
            peaks = []
        self._peaks_ready.emit(cache_key, peaks)

    def _apply_peaks(self, cache_key: tuple[str, int, int, int], peaks: list[float]) -> None:
        if cache_key != self._cache_key:
            return
        _WAVEFORM_CACHE[cache_key] = peaks
        self._peaks = peaks
        self._is_available = bool(peaks)
        self._is_loading = False
        self._did_attempt_load = True
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        colors = _mini_waveform_palette(self._theme_mode)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colors["background"]))
        painter.drawRoundedRect(rect, 11, 11)

        content = rect.adjusted(12, 8, -12, -8)
        center_y = content.center().y()
        painter.setPen(QPen(colors["midline"], 1))
        painter.drawLine(QPointF(content.left(), center_y), QPointF(content.right(), center_y))

        if not self._is_available:
            self._ensure_loading()
            _draw_waveform_placeholder(painter, content, colors["muted"])
            return

        painter.setPen(QPen(colors["wave"], 1))
        step = content.width() / max(1, len(self._peaks) - 1)
        max_height = content.height() * 0.46
        for index, peak in enumerate(self._peaks):
            x = content.left() + index * step
            height = max(1.0, peak * max_height)
            painter.drawLine(QPointF(x, center_y - height), QPointF(x, center_y + height))

    def _ensure_loading(self) -> None:
        if self._path is None or self._is_loading or self._is_available or self._did_attempt_load:
            return
        if self._cache_key is None:
            return
        self._is_loading = True
        self._did_attempt_load = True
        future = _WAVEFORM_EXECUTOR.submit(build_waveform_peaks, self._path, _WAVEFORM_POINT_COUNT)
        future.add_done_callback(lambda completed, key=self._cache_key: self._emit_peaks(key, completed))


def _mini_waveform_palette(theme_mode: str) -> dict[str, QColor]:
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


def _draw_waveform_placeholder(painter: QPainter, content: QRectF, color: QColor) -> None:
    painter.setPen(QPen(color, 1))
    center_y = content.center().y()
    step = max(6.0, content.width() / 24)
    max_height = content.height() * 0.28
    x = content.left()
    index = 0
    while x <= content.right():
        height = max_height * (0.25 + 0.75 * ((index % 5) / 4))
        painter.drawLine(QPointF(x, center_y - height), QPointF(x, center_y + height))
        x += step
        index += 1
