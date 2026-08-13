from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QEvent, QUrl, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QResizeEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_placeholder,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.widgets import DangerIconButton, FileDropCard, ScrollSafeComboBox, SvgIconButton
from jang_app.services.i18n import tr
from jang_app.services.studio_session import MEDIA_FILL, StudioMediaSettings
from jang_app.services.video_source import VideoSource


class MediaPlayerAdapter(Protocol):
    def position(self) -> int: ...

    def setPosition(self, position: int) -> None: ...  # noqa: N802

    def playbackState(self): ...  # noqa: N802

    def play(self) -> None: ...

    def pause(self) -> None: ...


class VideoPlaybackSynchronizer:
    def __init__(self, player: MediaPlayerAdapter, drift_limit_ms: int = 180) -> None:
        self._player = player
        self._drift_limit_ms = max(0, int(drift_limit_ms))

    def sync(self, position_ms: int, is_playing: bool) -> None:
        target = max(0, int(position_ms))
        if abs(self._player.position() - target) > self._drift_limit_ms:
            self._player.setPosition(target)
        player_is_running = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if is_playing and not player_is_running:
            self._player.play()
        elif not is_playing and player_is_running:
            self._player.pause()


class VideoPreviewPanel(QFrame):
    browse_requested = Signal()
    files_dropped = Signal(object)
    url_requested = Signal(str)
    open_location_requested = Signal(object)
    clear_requested = Signal()
    download_requested = Signal()
    saved_source_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VideoPreviewPanel")
        self.setMinimumSize(440, 420)
        self._source = VideoSource()
        self._original_song_url = ""
        self._saved_sources: tuple[VideoSource, ...] = ()
        self._active = False
        self._enabled = False
        self._running = False
        self._preview_path: Path | None = None
        self._preview_kind = ""

        self.title_label = QLabel("Media")
        self.title_label.setObjectName("SectionTitle")
        self.source_label = QLabel("")
        self.source_label.setObjectName("MutedText")
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.saved_source_combo = ScrollSafeComboBox()
        self.saved_source_combo.setObjectName("VideoSourceCombo")
        self.saved_source_combo.setMinimumWidth(170)
        self.saved_source_combo.setMaximumWidth(260)
        self.saved_source_combo.setMaxVisibleItems(8)
        set_translated_tooltip(self.saved_source_combo, "Reuse saved media")
        self.saved_source_combo.activated.connect(self._select_saved_source)
        self.saved_source_combo.hide()

        self.edit_button = SvgIconButton("edit", size=30)
        self.edit_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.edit_button, "Change media source")
        self.edit_button.clicked.connect(self._show_source_editor)
        self.edit_button.hide()

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.source_label, 1)
        header.addWidget(self.saved_source_combo, 0)
        header.addWidget(self.edit_button, 0)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoCanvas")
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.image_widget = _ImageCanvas()

        self.source_editor = QFrame()
        self.source_editor.setObjectName("VideoSourceCanvas")
        source_layout = QVBoxLayout(self.source_editor)
        source_layout.setContentsMargins(28, 28, 28, 28)
        source_layout.setSpacing(12)
        source_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.source_card = QFrame()
        self.source_card.setObjectName("VideoSourceCard")
        self.source_badge = QLabel("")
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(76)
        self.source_name = QLabel("")
        self.source_name.setObjectName("CardTitle")
        self.source_detail = QLabel("")
        self.source_detail.setObjectName("MutedText")
        self.source_detail.setWordWrap(True)
        self.source_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        source_text = QVBoxLayout()
        source_text.setContentsMargins(0, 0, 0, 0)
        source_text.setSpacing(3)
        source_text.addWidget(self.source_name)
        source_text.addWidget(self.source_detail)

        self.download_button = SvgIconButton("download", size=30)
        self.download_button.setObjectName("VideoSourceActionButton")
        set_translated_tooltip(self.download_button, "Download Video")
        self.download_button.clicked.connect(self.download_requested.emit)
        self.open_button = SvgIconButton("folder", size=30)
        self.open_button.setObjectName("VideoSourceActionButton")
        set_translated_tooltip(self.open_button, "Open media location")
        self.open_button.clicked.connect(self._open_location)
        self.clear_button = DangerIconButton(size=30)
        set_translated_tooltip(self.clear_button, "Clear media source")
        self.clear_button.clicked.connect(self.clear_requested.emit)

        source_card_layout = QHBoxLayout(self.source_card)
        source_card_layout.setContentsMargins(14, 12, 14, 12)
        source_card_layout.setSpacing(10)
        source_card_layout.addWidget(self.source_badge, 0)
        source_card_layout.addLayout(source_text, 1)
        source_card_layout.addWidget(self.download_button, 0)
        source_card_layout.addWidget(self.open_button, 0)
        source_card_layout.addWidget(self.clear_button, 0)

        self.url_field = _VideoUrlField()
        self.url_field.submitted.connect(self.url_requested.emit)
        self.url_field.original_requested.connect(self._use_original_song_url)

        self.drop_card = FileDropCard()
        self.drop_card.setMinimumHeight(124)
        set_translated_text(self.drop_card.title_label, "Drop Media")
        set_translated_tooltip(self.drop_card.file_button, "Add media file")
        self.drop_card.browse_requested.connect(self.browse_requested.emit)
        self.drop_card.files_dropped.connect(self.files_dropped.emit)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ActionProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        source_layout.addWidget(self.source_card, 0)
        source_layout.addWidget(self.url_field, 0)
        source_layout.addWidget(self.drop_card, 1)
        source_layout.addWidget(self.progress_bar, 0)
        source_layout.addWidget(self.status_label, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.source_editor)
        self.stack.addWidget(self.video_widget)
        self.stack.addWidget(self.image_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setMuted(True)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.errorOccurred.connect(self._on_media_error)
        self.synchronizer = VideoPlaybackSynchronizer(self.media_player)
        self.set_source(VideoSource(), enabled=False)

    @property
    def has_local_source(self) -> bool:
        path = self._source.path
        return path is not None and path.is_file()

    def set_source(
        self,
        source: VideoSource,
        *,
        enabled: bool,
        original_song_url: str = "",
        saved_sources: tuple[VideoSource, ...] = (),
    ) -> None:
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self._preview_path = None
        self._preview_kind = ""
        self._source = source
        self._enabled = enabled
        self._original_song_url = original_song_url.strip()
        self.url_field.set_original_url_available(bool(self._original_song_url))
        self._populate_saved_sources(saved_sources)

        configured = source.is_configured
        self.source_card.setVisible(configured)
        self.source_label.setText(source.display_name if configured else "")
        self.source_label.setToolTip(str(source.path) if source.path is not None else source.url)
        self.drop_card.set_selected_text("")
        if configured:
            set_translated_text(self.source_badge, _source_badge(source))
            self.source_badge.setProperty("sourceType", _source_type(source))
            self.source_badge.style().unpolish(self.source_badge)
            self.source_badge.style().polish(self.source_badge)
            self.source_name.setText(source.display_name)
            self.source_detail.setText(str(source.path) if source.path is not None else source.url)
            self.open_button.setVisible(source.path is not None)
            self.clear_button.setVisible(not source.inherited)
            self.download_button.setVisible(source.kind == "youtube" and source.path is None)

        if self.has_local_source:
            path = source.path.expanduser().resolve()
            self._activate_preview_path(path, source.media_kind)
            self.edit_button.show()
        else:
            self.stack.setCurrentWidget(self.source_editor)
            self.edit_button.hide()
        self.set_progress(0)
        self.set_status("")
        self._sync_controls()

    def set_running(self, running: bool) -> None:
        self._running = running
        self._sync_controls()

    def set_compact_mode(self, compact: bool) -> None:
        """Fit the source editor above a timeline without hiding its controls."""
        if compact:
            self.setMinimumSize(320, 190)
            self.setMaximumHeight(16_777_215)
            self.layout().setContentsMargins(14, 12, 14, 14)
            self.layout().setSpacing(8)
            self.source_editor.layout().setContentsMargins(12, 8, 12, 8)
            self.source_editor.layout().setSpacing(7)
            self.drop_card.setMinimumHeight(96)
            self.drop_card.setMaximumHeight(16_777_215)
            self.drop_card.set_compact_mode(True)
            return
        self.setMinimumSize(440, 420)
        self.setMaximumHeight(16_777_215)
        self.layout().setContentsMargins(18, 16, 18, 18)
        self.layout().setSpacing(12)
        self.source_editor.layout().setContentsMargins(28, 28, 28, 28)
        self.source_editor.layout().setSpacing(12)
        self.drop_card.setMinimumHeight(124)
        self.drop_card.setMaximumHeight(16_777_215)
        self.drop_card.set_compact_mode(False)

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_bar.setVisible(0 < progress < 100)

    def set_status(self, status: str, detail: str = "") -> None:
        value = status.strip()
        set_translated_text(self.status_label, value)
        self.status_label.setToolTip(detail)
        self.status_label.setVisible(bool(value))

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if not self._active:
            self.synchronizer.sync(self.media_player.position(), False)

    def sync_playback(self, position_ms: int, is_playing: bool) -> None:
        if not self._active or not self.has_local_source or self._source.media_kind != "video":
            return
        self._activate_preview_path(self._source.path, "video")
        self.synchronizer.sync(position_ms, is_playing)

    def sync_timeline_media(
        self,
        path: Path | None,
        media_kind: str,
        source_position_ms: int,
        is_playing: bool,
        settings: StudioMediaSettings | None = None,
    ) -> None:
        if not self._active:
            return
        if path is None or not path.is_file():
            self.synchronizer.sync(self.media_player.position(), False)
            self.media_player.setSource(QUrl())
            self._preview_path = None
            self._preview_kind = ""
            self.audio_output.setMuted(True)
            self.image_widget.clear_source()
            self.stack.setCurrentWidget(self.image_widget)
            return
        resolved = path.expanduser().resolve()
        self._activate_preview_path(resolved, media_kind, settings)
        if media_kind == "video":
            self.synchronizer.sync(source_position_ms, is_playing)

    def stop(self) -> None:
        self.media_player.stop()

    def set_theme_mode(self, theme_mode: str) -> None:
        for button in (
            self.edit_button,
            self.download_button,
            self.open_button,
            self.clear_button,
            self.drop_card.file_button,
        ):
            button.set_theme_mode(theme_mode)
        self.url_field.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_text(self.title_label, "Media")
        set_translated_tooltip(self.edit_button, "Change media source")
        set_translated_tooltip(self.saved_source_combo, "Reuse saved media")
        set_translated_tooltip(self.open_button, "Open media location")
        set_translated_tooltip(self.clear_button, "Clear media source")
        set_translated_tooltip(self.download_button, "Download Video")
        set_translated_text(self.drop_card.title_label, "Drop Media")
        set_translated_tooltip(self.drop_card.file_button, "Add media file")
        self.url_field.apply_language()
        self._populate_saved_sources(self._saved_sources)
        if self._source.is_configured:
            set_translated_text(self.source_badge, _source_badge(self._source))

    def _show_source_editor(self) -> None:
        self.synchronizer.sync(self.media_player.position(), False)
        self.stack.setCurrentWidget(self.source_editor)
        self.edit_button.hide()

    def _populate_saved_sources(self, sources: tuple[VideoSource, ...]) -> None:
        self._saved_sources = sources
        local_sources = tuple(
            source
            for source in sources
            if source.path is not None and source.path.is_file()
        )
        self.saved_source_combo.blockSignals(True)
        self.saved_source_combo.clear()
        active_path = self._source.path.resolve() if self._source.path is not None else None
        active_index = -1
        if active_path is None:
            self.saved_source_combo.addItem(
                tr("Saved media ({count})", count=len(local_sources)),
                None,
            )
        for source in local_sources:
            path = source.path.resolve()
            self.saved_source_combo.addItem(source.display_name, path)
            index = self.saved_source_combo.count() - 1
            self.saved_source_combo.setItemData(index, str(path), Qt.ItemDataRole.ToolTipRole)
            if path == active_path:
                active_index = index
        if active_index >= 0:
            self.saved_source_combo.setCurrentIndex(active_index)
        self.saved_source_combo.blockSignals(False)
        has_alternative = any(
            source.path is not None and source.path.resolve() != active_path
            for source in local_sources
        )
        self.saved_source_combo.setVisible(
            (active_path is None and bool(local_sources)) or has_alternative
        )

    def _select_saved_source(self, index: int) -> None:
        path = self.saved_source_combo.itemData(index)
        if isinstance(path, Path):
            self.saved_source_requested.emit(path)

    def _use_original_song_url(self) -> None:
        if self._original_song_url:
            self.url_field.set_url(self._original_song_url)
            self.url_requested.emit(self._original_song_url)

    def _open_location(self) -> None:
        if self._source.path is not None:
            self.open_location_requested.emit(self._source.path)

    def _sync_controls(self) -> None:
        controls_enabled = self._enabled and not self._running
        self.url_field.setEnabled(controls_enabled)
        self.drop_card.setEnabled(controls_enabled)
        self.open_button.setEnabled(controls_enabled and self._source.path is not None)
        self.clear_button.setEnabled(
            controls_enabled and self._source.is_configured and not self._source.inherited
        )
        self.download_button.setEnabled(
            controls_enabled and self._source.kind == "youtube" and self._source.path is None
        )

    def _on_media_error(self, _error, error_text: str) -> None:
        if error_text:
            self.source_label.setToolTip(error_text)

    def _activate_preview_path(
        self,
        path: Path,
        media_kind: str,
        settings: StudioMediaSettings | None = None,
    ) -> None:
        resolved = path.expanduser().resolve()
        media_settings = settings or StudioMediaSettings()
        self.audio_output.setMuted(
            media_kind != "video" or not media_settings.source_audio_enabled
        )
        if self._preview_path == resolved and self._preview_kind == media_kind:
            if media_kind == "image":
                self.image_widget.set_media_settings(media_settings)
            return
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self._preview_path = resolved
        self._preview_kind = media_kind
        if media_kind == "image":
            self.image_widget.set_path(resolved)
            self.image_widget.set_media_settings(media_settings)
            self.stack.setCurrentWidget(self.image_widget)
            return
        self.media_player.setSource(QUrl.fromLocalFile(str(resolved)))
        self.stack.setCurrentWidget(self.video_widget)


class _ImageCanvas(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VideoCanvas")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source = QPixmap()
        self._settings = StudioMediaSettings()

    def set_path(self, path: Path) -> None:
        self._source = QPixmap(str(path))
        self._refresh_pixmap()

    def clear_source(self) -> None:
        self._source = QPixmap()
        self.clear()

    def set_media_settings(self, settings: StudioMediaSettings) -> None:
        self._settings = settings
        self._refresh_pixmap()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            self.clear()
            return
        source_width = max(1, self._source.width())
        source_height = max(1, self._source.height())
        fit_scale = min(self.width() / source_width, self.height() / source_height)
        if self._settings.fit_mode == MEDIA_FILL:
            fit_scale = max(self.width() / source_width, self.height() / source_height)
        scale = fit_scale * self._settings.scale_percent / 100
        width = max(1, round(source_width * scale))
        height = max(1, round(source_height * scale))
        scaled = self._source.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(self.size())
        canvas.fill(Qt.GlobalColor.black)
        x = (self.width() - width) / 2 + self.width() * self._settings.offset_x_percent / 100
        y = (self.height() - height) / 2 + self.height() * self._settings.offset_y_percent / 100
        painter = QPainter(canvas)
        painter.drawPixmap(round(x), round(y), scaled)
        painter.end()
        self.setPixmap(canvas)


class _VideoUrlField(QFrame):
    submitted = Signal(str)
    original_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VideoUrlField")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._original_url_available = False

        self.edit = QLineEdit()
        self.edit.setObjectName("VideoUrlEdit")
        self.edit.setFrame(False)
        set_translated_placeholder(self.edit, "Video URL")
        self.edit.returnPressed.connect(self._submit)
        self.edit.textChanged.connect(self._sync_submit_button)
        self.edit.installEventFilter(self)

        self.original_button = SvgIconButton("youtube", size=30)
        self.original_button.setObjectName("VideoOriginalUrlButton")
        set_translated_tooltip(self.original_button, "Use song's YouTube URL")
        self.original_button.clicked.connect(self.original_requested.emit)
        self.original_button.hide()

        self.submit_button = SvgIconButton("link", size=30)
        self.submit_button.setObjectName("EmbeddedActionButton")
        set_translated_tooltip(self.submit_button, "Use URL")
        self.submit_button.clicked.connect(self._submit)

        self.original_slot = QWidget()
        self.original_slot.setObjectName("VideoOriginalUrlSlot")
        self.original_slot.setFixedSize(30, 30)
        original_layout = QVBoxLayout(self.original_slot)
        original_layout.setContentsMargins(0, 0, 0, 0)
        original_layout.addWidget(self.original_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 5, 5)
        layout.setSpacing(5)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.original_slot, 0)
        layout.addWidget(self.submit_button, 0)
        self._sync_original_button()
        self._sync_submit_button()

    def set_original_url_available(self, available: bool) -> None:
        self._original_url_available = bool(available)
        self._sync_original_button()

    def set_url(self, url: str) -> None:
        self.edit.setText(url)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.original_button.set_theme_mode(theme_mode)
        self.submit_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_placeholder(self.edit, "Video URL")
        set_translated_tooltip(self.original_button, "Use song's YouTube URL")
        set_translated_tooltip(self.submit_button, "Use URL")

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() in {QEvent.Type.Enter, QEvent.Type.Leave}:
            self._sync_original_button()
        return handled

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.edit and event.type() in {
            QEvent.Type.Enter,
            QEvent.Type.Leave,
            QEvent.Type.FocusIn,
            QEvent.Type.FocusOut,
        }:
            self._sync_original_button()
        return super().eventFilter(watched, event)

    def _submit(self) -> None:
        value = self.edit.text().strip()
        if value:
            self.submitted.emit(value)

    def _sync_original_button(self) -> None:
        self.original_slot.setVisible(self._original_url_available)
        hovered = self.underMouse() or self.edit.underMouse() or self.edit.hasFocus()
        self.original_button.setVisible(self._original_url_available and hovered)

    def _sync_submit_button(self) -> None:
        self.submit_button.setEnabled(bool(self.edit.text().strip()))


def _source_badge(source: VideoSource) -> str:
    if source.kind == "youtube":
        return "YOUTUBE"
    if source.kind == "url":
        return "URL"
    return "FILE"


def _source_type(source: VideoSource) -> str:
    return "youtube" if source.kind == "youtube" else "local"
