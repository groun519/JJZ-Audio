from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.share_progress_action import ShareProgressAction
from jang_app.qt_app.work_song_selector import WorkSongSelector
from jang_app.qt_app.widgets import SvgIconButton, TaskActionWidget
from jang_app.services.google_drive_share import drive_share_target_id
from jang_app.services.song_export import SongAudioExport
from jang_app.services.song_video_export import SongVideoExport


class ExportPage(QWidget):
    song_changed = Signal(str)
    audio_export_requested = Signal(str)
    video_export_requested = Signal(str)
    open_location_requested = Signal(object)
    share_requested = Signal(object)
    delete_share_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._export_dir: Path | None = None
        self._target_song_id = ""
        self._theme_mode = "white"
        self._sharing_enabled = True
        self._share_progress_by_id: dict[str, int] = {}
        self._shared_target_ids: set[str] = set()
        self._share_status_provider: Callable[[Path], bool] | None = None
        self.export_rows: list[_ExportRow] = []

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(380)
        left_panel.setMaximumWidth(460)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(14)

        target_label = QLabel("Export Song")
        target_label.setObjectName("SectionLabel")
        self.song_selector = WorkSongSelector(
            empty_text="Select export song",
            object_name="ExportSongCombo",
        )
        self.song_selector.setMinimumWidth(0)
        self.song_selector.song_changed.connect(self._on_song_changed)
        left_layout.addWidget(target_label, 0)
        left_layout.addWidget(self.song_selector, 0)

        self.audio_action = TaskActionWidget("Audio Mix", "Export")
        self.audio_action.triggered.connect(self._request_audio_export)
        self.audio_action.set_action_enabled(False)
        self.video_action = TaskActionWidget("Video Export", "Render")
        self.video_action.triggered.connect(self._request_video_export)
        self.video_action.set_action_enabled(False)
        left_layout.addWidget(self.audio_action, 0)
        left_layout.addWidget(self.video_action, 0)
        left_layout.addStretch(1)

        results_panel = QFrame()
        results_panel.setObjectName("Panel")
        results_layout = QVBoxLayout(results_panel)
        results_layout.setContentsMargins(20, 20, 20, 20)
        results_layout.setSpacing(14)

        title = QLabel("Exports")
        title.setObjectName("SectionTitle")
        self.open_folder_button = SvgIconButton("folder", size=34)
        self.open_folder_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_folder_button, "Open export location")
        self.open_folder_button.clicked.connect(self._open_export_location)
        self.open_folder_button.setEnabled(False)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title, 1)
        header.addWidget(self.open_folder_button, 0)

        self.export_content = QWidget()
        self.export_layout = QVBoxLayout(self.export_content)
        self.export_layout.setContentsMargins(0, 0, 0, 0)
        self.export_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setObjectName("ExportScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.export_content)

        results_layout.addLayout(header)
        results_layout.addWidget(scroll, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(left_panel, 0)
        layout.addWidget(results_panel, 1)
        self.set_exports((), (), None)

    def set_exports(
        self,
        audio_exports: tuple[SongAudioExport, ...],
        video_exports: tuple[SongVideoExport, ...],
        export_dir: Path | None,
    ) -> None:
        self._clear_rows()
        self._export_dir = export_dir
        self.open_folder_button.setEnabled(export_dir is not None)
        exports: list[tuple[SongAudioExport | SongVideoExport, str]] = [
            (exported, "AUDIO") for exported in audio_exports
        ] + [(exported, "VIDEO") for exported in video_exports]
        exports.sort(key=lambda item: item[0].modified_at, reverse=True)
        if not exports:
            empty_label = QLabel()
            empty_label.setObjectName("ExportEmptyState")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_translated_text(empty_label, "No exports yet.")
            self.export_layout.addWidget(empty_label, 1)
            return

        for exported, export_kind in exports:
            row = _ExportRow(exported, export_kind)
            row.set_theme_mode(self._theme_mode)
            row.set_sharing_enabled(self._sharing_enabled)
            row.set_shared(self._path_is_shared(exported.path, row.target_id))
            if row.target_id in self._share_progress_by_id:
                row.set_share_started()
                row.set_share_progress(self._share_progress_by_id[row.target_id])
            row.open_location_requested.connect(self.open_location_requested.emit)
            row.share_requested.connect(self.share_requested.emit)
            row.delete_share_requested.connect(self.delete_share_requested.emit)
            self.export_rows.append(row)
            self.export_layout.addWidget(row, 0)
        self.export_layout.addStretch(1)

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self.song_selector.set_songs(songs, selected_id)

    def selected_song_id(self) -> str:
        return self._target_song_id

    def set_target_song(
        self,
        song_id: str,
        *,
        audio_enabled: bool,
        video_enabled: bool,
    ) -> None:
        changed = song_id != self._target_song_id
        self._target_song_id = song_id
        self.song_selector.select_song(song_id)
        if changed:
            for action in (self.audio_action, self.video_action):
                action.set_progress(0)
                action.set_status("")
        self.audio_action.set_action_enabled(audio_enabled)
        self.video_action.set_action_enabled(video_enabled)

    def set_audio_running(self, running: bool) -> None:
        self.audio_action.set_running(running)

    def set_audio_progress(self, progress: int) -> None:
        self.audio_action.set_progress(progress)

    def set_audio_status(self, status: str, detail: str = "") -> None:
        self.audio_action.set_status(status)
        self.audio_action.status_label.setToolTip(detail)

    def set_video_running(self, running: bool) -> None:
        self.video_action.set_running(running)

    def set_video_progress(self, progress: int) -> None:
        self.video_action.set_progress(progress)

    def set_video_status(self, status: str, detail: str = "") -> None:
        self.video_action.set_status(status)
        self.video_action.status_label.setToolTip(detail)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.open_folder_button.set_theme_mode(theme_mode)
        for row in self.export_rows:
            row.set_theme_mode(theme_mode)

    def set_sharing_enabled(self, is_enabled: bool) -> None:
        self._sharing_enabled = is_enabled
        for row in self.export_rows:
            row.set_sharing_enabled(is_enabled)

    def set_share_status_provider(self, provider: Callable[[Path], bool]) -> None:
        self._share_status_provider = provider
        for row in self.export_rows:
            row.set_shared(
                self._path_is_shared(row.path, row.target_id, refresh=True)
            )

    def set_share_started(self, target_id: str) -> None:
        row = self._row_for_target(target_id)
        if row is None:
            return
        self._share_progress_by_id[target_id] = 0
        row.set_share_started()

    def set_share_progress(self, target_id: str, progress: int) -> None:
        if target_id not in self._share_progress_by_id:
            return
        value = max(0, min(100, int(progress)))
        self._share_progress_by_id[target_id] = value
        row = self._row_for_target(target_id)
        if row is not None:
            row.set_share_progress(value)

    def set_share_completed(self, target_id: str) -> None:
        self._share_progress_by_id.pop(target_id, None)
        self._shared_target_ids.add(target_id)
        row = self._row_for_target(target_id)
        if row is not None:
            row.set_share_completed()

    def set_share_failed(self, target_id: str) -> None:
        self._share_progress_by_id.pop(target_id, None)
        row = self._row_for_target(target_id)
        if row is not None:
            row.set_share_failed()

    def set_share_deleted(self, target_id: str) -> None:
        self._share_progress_by_id.pop(target_id, None)
        self._shared_target_ids.discard(target_id)
        row = self._row_for_target(target_id)
        if row is not None:
            row.set_share_deleted()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.song_selector.apply_language()
        set_translated_tooltip(self.open_folder_button, "Open export location")

    def _request_audio_export(self) -> None:
        self.audio_export_requested.emit(self._target_song_id)

    def _request_video_export(self) -> None:
        self.video_export_requested.emit(self._target_song_id)

    def _on_song_changed(self, song_id: str) -> None:
        self.set_target_song(song_id, audio_enabled=False, video_enabled=False)
        self.song_changed.emit(song_id)

    def _open_export_location(self) -> None:
        if self._export_dir is not None:
            self.open_location_requested.emit(self._export_dir)

    def _clear_rows(self) -> None:
        self.export_rows = []
        while self.export_layout.count():
            item = self.export_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _row_for_target(self, target_id: str) -> "_ExportRow | None":
        return next((row for row in self.export_rows if row.target_id == target_id), None)

    def _path_is_shared(
        self,
        path: Path,
        target_id: str,
        *,
        refresh: bool = False,
    ) -> bool:
        if not refresh and target_id in self._shared_target_ids:
            return True
        is_shared = False
        if self._share_status_provider is not None:
            try:
                is_shared = self._share_status_provider(path)
            except OSError:
                is_shared = False
        if is_shared:
            self._shared_target_ids.add(target_id)
        else:
            self._shared_target_ids.discard(target_id)
        return is_shared


class _ExportRow(QFrame):
    open_location_requested = Signal(object)
    share_requested = Signal(object)
    delete_share_requested = Signal(object)

    def __init__(self, exported: SongAudioExport | SongVideoExport, export_kind: str) -> None:
        super().__init__()
        self.setObjectName("ExportRow")
        self.path = exported.path
        self.target_id = drive_share_target_id(exported.path)

        badge = QLabel(export_kind)
        badge.setObjectName("SourceBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(58)
        badge.setProperty("sourceType", "output" if export_kind == "VIDEO" else "local")

        name_label = QLabel(exported.path.name)
        name_label.setObjectName("ExportName")
        name_label.setToolTip(str(exported.path))

        meta_label = QLabel(f"{_size_label(exported.size_bytes)}  /  {_timestamp(exported.modified_at)}")
        meta_label.setObjectName("ExportMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(name_label)
        text_layout.addWidget(meta_label)

        self.open_button = SvgIconButton("folder", size=30)
        set_translated_tooltip(self.open_button, "Open file location")
        self.open_button.clicked.connect(lambda: self.open_location_requested.emit(exported.path))
        self.share_action = ShareProgressAction(button_size=30, parent=self)
        self.share_action.requested.connect(lambda: self.share_requested.emit(exported.path))
        self.share_action.delete_requested.connect(
            lambda: self.delete_share_requested.emit(exported.path)
        )
        self.share_button = self.share_action.button

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(badge, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.share_action, 0)
        layout.addWidget(self.open_button, 0)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.share_action.set_theme_mode(theme_mode)
        self.open_button.set_theme_mode(theme_mode)

    def set_sharing_enabled(self, is_enabled: bool) -> None:
        self.share_action.set_feature_enabled(is_enabled)

    def set_share_started(self) -> None:
        self.share_action.set_running(True)

    def set_share_progress(self, progress: int) -> None:
        self.share_action.set_progress(progress)

    def set_share_completed(self) -> None:
        self.share_action.set_completed()

    def set_share_failed(self) -> None:
        self.share_action.set_failed()

    def set_shared(self, is_shared: bool) -> None:
        self.share_action.set_shared(is_shared)

    def set_share_deleted(self) -> None:
        self.share_action.set_running(False)
        self.share_action.set_deleted()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.share_action.set_actions_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.share_action.set_actions_expanded(False)
        super().leaveEvent(event)


def _size_label(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return ""


def _timestamp(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%y/%m/%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""
