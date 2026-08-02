from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QLabel, QStackedWidget, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
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
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VideoPreviewPanel")
        self.setMinimumHeight(280)
        self._source = VideoSource()
        self._active = False

        self.title_label = QLabel("Video Preview")
        self.title_label.setObjectName("SectionTitle")
        self.source_label = QLabel("")
        self.source_label.setObjectName("MutedText")
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)
        header.addWidget(self.title_label)
        header.addWidget(self.source_label)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoCanvas")
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)

        self.empty_widget = QFrame()
        self.empty_widget.setObjectName("VideoCanvas")
        self.empty_label = QLabel("Add or download a video")
        self.empty_label.setObjectName("VideoEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setContentsMargins(20, 20, 20, 20)
        empty_layout.addWidget(self.empty_label, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty_widget)
        self.stack.addWidget(self.video_widget)

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
        self.set_source(VideoSource())

    @property
    def has_local_source(self) -> bool:
        path = self._source.path
        return path is not None and path.is_file()

    def set_source(self, source: VideoSource) -> None:
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self._source = source
        if self.has_local_source:
            path = source.path.expanduser().resolve()
            self.media_player.setSource(QUrl.fromLocalFile(str(path)))
            self.source_label.setText(source.display_name)
            self.source_label.setToolTip(str(path))
            self.stack.setCurrentWidget(self.video_widget)
            return

        self.source_label.setText(source.display_name if source.is_configured else "")
        self.source_label.setToolTip(source.url)
        set_translated_text(
            self.empty_label,
            "Download video to preview" if source.kind == "youtube" else "Add or download a video",
        )
        self.stack.setCurrentWidget(self.empty_widget)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if not self._active:
            self.synchronizer.sync(self.media_player.position(), False)

    def sync_playback(self, position_ms: int, is_playing: bool) -> None:
        if not self._active or not self.has_local_source:
            return
        self.synchronizer.sync(position_ms, is_playing)

    def stop(self) -> None:
        self.media_player.stop()

    def apply_language(self) -> None:
        apply_widget_language(self)
        if not self.has_local_source:
            set_translated_text(
                self.empty_label,
                "Download video to preview"
                if self._source.kind == "youtube"
                else "Add or download a video",
            )

    def _on_media_error(self, _error, error_text: str) -> None:
        if error_text:
            self.source_label.setToolTip(error_text)
