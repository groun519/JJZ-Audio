from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QVBoxLayout

from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_placeholder,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.widgets import FeedbackButton, FileDropCard, SvgIconButton
from jang_app.services.video_source import VideoSource


class VideoSourcePanel(QFrame):
    browse_requested = Signal()
    files_dropped = Signal(object)
    url_requested = Signal(str)
    open_location_requested = Signal(object)
    clear_requested = Signal()
    download_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._enabled = False
        self._running = False
        self._source = VideoSource()
        self._theme_mode = "white"

        title = QLabel("Video Source")
        title.setObjectName("SectionTitle")

        self.source_card = QFrame()
        self.source_card.setObjectName("InsetCard")
        self.source_badge = QLabel("")
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(76)
        self.source_name = QLabel("")
        self.source_name.setObjectName("CardTitle")
        self.source_detail = QLabel("")
        self.source_detail.setObjectName("MutedText")
        self.source_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_detail.setWordWrap(True)

        source_text = QVBoxLayout()
        source_text.setContentsMargins(0, 0, 0, 0)
        source_text.setSpacing(4)
        source_text.addWidget(self.source_name)
        source_text.addWidget(self.source_detail)

        self.open_button = SvgIconButton("folder", size=30)
        set_translated_tooltip(self.open_button, "Open video location")
        self.open_button.clicked.connect(self._open_location)
        self.clear_button = SvgIconButton("trash", size=30)
        set_translated_tooltip(self.clear_button, "Clear video source")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.download_button = FeedbackButton("Download")
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self.download_requested.emit)

        source_layout = QHBoxLayout(self.source_card)
        source_layout.setContentsMargins(14, 12, 14, 12)
        source_layout.setSpacing(10)
        source_layout.addWidget(self.source_badge, 0)
        source_layout.addLayout(source_text, 1)
        source_layout.addWidget(self.download_button, 0)
        source_layout.addWidget(self.open_button, 0)
        source_layout.addWidget(self.clear_button, 0)

        self.url_edit = QLineEdit()
        set_translated_placeholder(self.url_edit, "Video URL")
        self.url_edit.returnPressed.connect(self._submit_url)
        self.url_button = FeedbackButton("Use URL")
        self.url_button.setObjectName("PrimaryButton")
        self.url_button.clicked.connect(self._submit_url)
        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(10)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.url_button, 0)

        self.drop_card = FileDropCard()
        self.drop_card.setMinimumHeight(112)
        set_translated_text(self.drop_card.title_label, "Drop Video")
        set_translated_tooltip(self.drop_card.file_button, "Add video file")
        self.drop_card.browse_requested.connect(self.browse_requested.emit)
        self.drop_card.files_dropped.connect(self.files_dropped.emit)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setObjectName("ActionProgress")
        self.progress_bar.hide()
        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        self.status_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self.source_card)
        layout.addLayout(url_row)
        layout.addWidget(self.drop_card)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.set_source(VideoSource(), enabled=False)

    def set_source(self, source: VideoSource, *, enabled: bool) -> None:
        self._source = source
        self._enabled = enabled
        configured = source.is_configured
        self.source_card.setVisible(configured)
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
        self.drop_card.set_selected_text(source.display_name if configured else "")
        self.set_progress(0)
        self.set_status("")
        self._sync_controls()

    def set_running(self, running: bool) -> None:
        self._running = running
        self._sync_controls()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_bar.setVisible(0 < progress < 100)

    def set_status(self, status: str, detail: str = "") -> None:
        value = status.strip()
        set_translated_text(self.status_label, value)
        self.status_label.setToolTip(detail)
        self.status_label.setVisible(bool(value))

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.drop_card.file_button.set_theme_mode(theme_mode)
        self.open_button.set_theme_mode(theme_mode)
        self.clear_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_placeholder(self.url_edit, "Video URL")
        set_translated_text(self.drop_card.title_label, "Drop Video")
        set_translated_tooltip(self.drop_card.file_button, "Add video file")
        set_translated_tooltip(self.open_button, "Open video location")
        set_translated_tooltip(self.clear_button, "Clear video source")
        set_translated_text(self.download_button, "Download")
        if self._source.is_configured:
            set_translated_text(self.source_badge, _source_badge(self._source))

    def _submit_url(self) -> None:
        value = self.url_edit.text().strip()
        if value:
            self.url_requested.emit(value)

    def _open_location(self) -> None:
        if self._source.path is not None:
            self.open_location_requested.emit(self._source.path)

    def _sync_controls(self) -> None:
        controls_enabled = self._enabled and not self._running
        self.url_edit.setEnabled(controls_enabled)
        self.url_button.setEnabled(controls_enabled)
        self.drop_card.setEnabled(controls_enabled)
        self.open_button.setEnabled(controls_enabled and self._source.path is not None)
        self.clear_button.setEnabled(controls_enabled and self._source.is_configured and not self._source.inherited)
        self.download_button.setEnabled(
            controls_enabled and self._source.kind == "youtube" and self._source.path is None
        )


def _source_badge(source: VideoSource) -> str:
    if source.kind == "youtube":
        return "YOUTUBE"
    if source.kind == "url":
        return "URL"
    return "FILE"


def _source_type(source: VideoSource) -> str:
    return "youtube" if source.kind == "youtube" else "local"
