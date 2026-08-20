from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.audio_export_controls import AudioExportControls
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.share_progress_action import ShareProgressAction
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.video_export_controls import VideoExportControls
from jang_app.qt_app.work_song_selector import WorkSongSelector
from jang_app.qt_app.widgets import (
    DangerIconButton,
    FeedbackButton,
    SvgIconButton,
)
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.services.google_drive_share import drive_share_target_id
from jang_app.services.song_export import SongAudioExport
from jang_app.services.song_video_export import SongVideoExport


EXPORT_MODE_AUDIO = "audio"
EXPORT_MODE_VIDEO = "video"


class ExportPage(QWidget):
    song_changed = Signal(str)
    audio_export_requested = Signal(str, object)
    video_export_requested = Signal(str, object)
    open_location_requested = Signal(object)
    share_requested = Signal(object)
    delete_share_requested = Signal(object)
    preview_requested = Signal(object)
    preview_play_toggled = Signal(object)
    preview_seek_requested = Signal(object, int)
    rename_requested = Signal(object, str)
    remove_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._export_dir: Path | None = None
        self._target_song_id = ""
        self._theme_mode = "white"
        self._sharing_enabled = True
        self._share_progress_by_id: dict[str, int] = {}
        self._shared_target_ids: set[str] = set()
        self._share_status_provider: Callable[[Path], bool] | None = None
        self._preview_path: Path | None = None
        self._audio_running = False
        self._video_running = False
        self.export_rows: list[_ExportRow] = []

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(380)
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

        mode_control = QFrame()
        mode_control.setObjectName("SegmentedControl")
        mode_layout = QHBoxLayout(mode_control)
        mode_layout.setContentsMargins(4, 4, 4, 4)
        mode_layout.setSpacing(4)
        self.export_mode_group = QButtonGroup(self)
        self.export_mode_group.setExclusive(True)
        self.export_mode_buttons: dict[str, FeedbackButton] = {}
        for mode, label in (
            (EXPORT_MODE_AUDIO, "Audio Export"),
            (EXPORT_MODE_VIDEO, "Video Export"),
        ):
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            set_translated_text(button, label)
            button.clicked.connect(
                lambda _checked=False, selected=mode: self.set_export_mode(selected)
            )
            self.export_mode_group.addButton(button)
            self.export_mode_buttons[mode] = button
            mode_layout.addWidget(button, 1)

        self.audio_controls = AudioExportControls()
        self.audio_controls.triggered.connect(self._request_audio_export)
        self.audio_controls.set_action_enabled(False)
        self.video_controls = VideoExportControls()
        self.video_controls.triggered.connect(self._request_video_export)
        self.video_controls.set_action_enabled(False)
        self.video_action = self.video_controls
        left_layout.addWidget(mode_control, 0)
        left_layout.addWidget(self.audio_controls, 0)
        left_layout.addWidget(self.video_controls, 0)
        left_layout.addStretch(1)
        self.set_export_mode(EXPORT_MODE_AUDIO)

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
        layout.setSpacing(0)
        self.workspace_splitter = create_workspace_splitter(
            (left_panel, results_panel),
            object_name="ExportWorkspaceSplitter",
            sizes=(420, 1180),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        layout.addWidget(self.workspace_splitter, 1)
        self.set_exports((), (), None)

    def set_exports(
        self,
        audio_exports: tuple[SongAudioExport, ...],
        video_exports: tuple[SongVideoExport, ...],
        export_dir: Path | None,
    ) -> None:
        preview_path = self._preview_path
        self._clear_rows()
        self._export_dir = export_dir
        self.open_folder_button.setEnabled(export_dir is not None)
        exports: list[tuple[SongAudioExport | SongVideoExport, str]] = [
            (exported, "AUDIO") for exported in audio_exports
        ] + [(exported, "VIDEO") for exported in video_exports]
        exports.sort(key=lambda item: item[0].modified_at, reverse=True)
        if not exports:
            self._preview_path = None
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
            row.preview_requested.connect(self.preview_requested.emit)
            row.preview_play_toggled.connect(self.preview_play_toggled.emit)
            row.preview_seek_requested.connect(self.preview_seek_requested.emit)
            row.rename_requested.connect(self.rename_requested.emit)
            row.remove_requested.connect(self.remove_requested.emit)
            self.export_rows.append(row)
            self.export_layout.addWidget(row, 0)
        preview_row = self._row_for_path(preview_path) if preview_path is not None else None
        if preview_row is not None and preview_row.can_preview:
            preview_row.set_preview_expanded(True)
        else:
            self._preview_path = None
        self.export_layout.addStretch(1)

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self.song_selector.set_songs(songs, selected_id)

    def selected_song_id(self) -> str:
        return self._target_song_id

    def selected_export_mode(self) -> str:
        for mode, button in self.export_mode_buttons.items():
            if button.isChecked():
                return mode
        return EXPORT_MODE_AUDIO

    def set_export_mode(self, mode: str) -> None:
        selected = mode if mode in self.export_mode_buttons else EXPORT_MODE_AUDIO
        self.export_mode_buttons[selected].setChecked(True)
        self.audio_controls.setVisible(selected == EXPORT_MODE_AUDIO)
        self.video_controls.setVisible(selected == EXPORT_MODE_VIDEO)

    def set_target_song(
        self,
        song_id: str,
        *,
        audio_enabled: bool,
        video_enabled: bool,
        duration_ms: int = 0,
    ) -> None:
        changed = song_id != self._target_song_id
        self._target_song_id = song_id
        self.song_selector.select_song(song_id)
        self.audio_controls.set_duration_ms(duration_ms)
        if changed:
            for action in (self.audio_controls, self.video_controls):
                action.set_progress(0)
                action.set_status("")
        self.audio_controls.set_action_enabled(audio_enabled)
        self.video_controls.set_action_enabled(video_enabled)

    def set_audio_running(self, running: bool) -> None:
        self._audio_running = running
        if running:
            self.set_export_mode(EXPORT_MODE_AUDIO)
        self.audio_controls.set_running(running)
        self._sync_mode_enabled()

    def set_audio_progress(self, progress: int) -> None:
        self.audio_controls.set_progress(progress)

    def set_audio_status(self, status: str, detail: str = "") -> None:
        self.audio_controls.set_status(status)
        self.audio_controls.status_label.setToolTip(detail)

    def set_video_running(self, running: bool) -> None:
        self._video_running = running
        if running:
            self.set_export_mode(EXPORT_MODE_VIDEO)
        self.video_controls.set_running(running)
        self._sync_mode_enabled()

    def set_video_progress(self, progress: int) -> None:
        self.video_controls.set_progress(progress)

    def set_video_status(self, status: str, detail: str = "") -> None:
        self.video_controls.set_status(status)
        self.video_controls.status_label.setToolTip(detail)

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

    def set_preview_expanded(self, path: Path, is_expanded: bool) -> None:
        resolved = path.expanduser().resolve()
        self._preview_path = resolved if is_expanded else None
        for row in self.export_rows:
            row.set_preview_expanded(
                is_expanded and row.path.expanduser().resolve() == resolved
            )

    def set_preview_queue(self, path: Path, duration_ms: int) -> None:
        row = self._row_for_path(path)
        if row is not None:
            row.set_preview_queue(duration_ms)

    def set_preview_position(self, path: Path, position_ms: int, duration_ms: int) -> None:
        row = self._row_for_path(path)
        if row is not None:
            row.set_preview_position(position_ms, duration_ms)

    def set_preview_playing(self, path: Path, is_playing: bool) -> None:
        row = self._row_for_path(path)
        if row is not None:
            row.set_preview_playing(is_playing)

    def clear_preview(self) -> None:
        self._preview_path = None
        for row in self.export_rows:
            row.set_preview_expanded(False)
            row.clear_preview()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self.song_selector.apply_language()
        self.audio_controls.apply_language()
        self.video_controls.apply_language()
        set_translated_tooltip(self.open_folder_button, "Open export location")
        for row in self.export_rows:
            row.apply_language()

    def _request_audio_export(self) -> None:
        self.audio_export_requested.emit(self._target_song_id, self.audio_controls.settings())

    def _request_video_export(self) -> None:
        self.video_export_requested.emit(self._target_song_id, self.video_controls.settings())

    def _sync_mode_enabled(self) -> None:
        enabled = not (self._audio_running or self._video_running)
        for button in self.export_mode_buttons.values():
            button.setEnabled(enabled)

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

    def _row_for_path(self, path: Path | None) -> "_ExportRow | None":
        if path is None:
            return None
        resolved = path.expanduser().resolve()
        return next(
            (
                row
                for row in self.export_rows
                if row.path.expanduser().resolve() == resolved
            ),
            None,
        )

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
    preview_requested = Signal(object)
    preview_play_toggled = Signal(object)
    preview_seek_requested = Signal(object, int)
    rename_requested = Signal(object, str)
    remove_requested = Signal(object)

    def __init__(self, exported: SongAudioExport | SongVideoExport, export_kind: str) -> None:
        super().__init__()
        self.setObjectName("ExportRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.path = exported.path
        self.target_id = drive_share_target_id(self.path)
        self.can_preview = export_kind == "AUDIO"
        self._is_editing = False
        self._is_hovered = False
        self._preview_expanded = False

        badge = QLabel(export_kind)
        badge.setObjectName("SourceBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(58)
        badge.setProperty("sourceType", "output" if export_kind == "VIDEO" else "local")

        self.name_label = OverflowTextLabel(
            exported.path.name,
            object_name="ExportName",
            fixed_height=22,
        )
        self.name_label.setToolTip(str(exported.path))
        self.name_edit = QLineEdit(exported.path.stem)
        self.name_edit.setObjectName("InlineTitleEdit")
        self.name_edit.hide()
        self.name_edit.returnPressed.connect(self._commit_rename)
        self.name_edit.editingFinished.connect(self._commit_rename)

        meta_label = QLabel(f"{_size_label(exported.size_bytes)}  /  {_timestamp(exported.modified_at)}")
        meta_label.setObjectName("ExportMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.name_edit)
        text_layout.addWidget(meta_label)

        self.rename_button = SvgIconButton("edit", size=30)
        set_translated_tooltip(self.rename_button, "Rename")
        self.rename_button.clicked.connect(self._begin_rename)

        self.open_button = SvgIconButton("folder", size=30)
        set_translated_tooltip(self.open_button, "Open file location")
        self.open_button.clicked.connect(lambda: self.open_location_requested.emit(self.path))
        self.remove_button = DangerIconButton(size=30)
        set_translated_tooltip(self.remove_button, "Delete export")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.path))
        self.share_action = ShareProgressAction(button_size=30, parent=self)
        self.share_action.requested.connect(lambda: self.share_requested.emit(self.path))
        self.share_action.delete_requested.connect(
            lambda: self.delete_share_requested.emit(self.path)
        )
        self.share_button = self.share_action.button

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        body_layout.addWidget(badge, 0)
        body_layout.addLayout(text_layout, 1)
        body_layout.addWidget(self.share_action, 0)
        body_layout.addWidget(self.rename_button, 0)
        body_layout.addWidget(self.open_button, 0)
        body_layout.addWidget(self.remove_button, 0)

        self.preview_divider = QFrame()
        self.preview_divider.setObjectName("LibraryPreviewDivider")
        self.preview_divider.setFixedHeight(1)
        self.preview_divider.hide()
        self.preview_transport = TransportControls()
        self.preview_transport.setObjectName("LibraryPreviewTransport")
        self.preview_transport.play_toggled.connect(
            lambda: self.preview_play_toggled.emit(self.path)
        )
        self.preview_transport.seek_requested.connect(
            lambda position_ms: self.preview_seek_requested.emit(self.path, position_ms)
        )
        self.preview_transport.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)
        layout.addLayout(body_layout)
        layout.addWidget(self.preview_divider)
        layout.addWidget(self.preview_transport)
        self._sync_action_visibility()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.share_action.set_theme_mode(theme_mode)
        self.open_button.set_theme_mode(theme_mode)
        self.rename_button.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)
        self.preview_transport.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_tooltip(self.rename_button, "Rename")
        set_translated_tooltip(self.open_button, "Open file location")
        set_translated_tooltip(self.remove_button, "Delete export")
        self.preview_transport.apply_language()

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

    def set_preview_expanded(self, is_expanded: bool) -> None:
        expanded = bool(is_expanded and self.can_preview)
        if expanded == self._preview_expanded:
            return
        self._preview_expanded = expanded
        self.preview_divider.setVisible(expanded)
        self.preview_transport.setVisible(expanded)
        if not expanded:
            self.preview_transport.set_playing(False)
        self.updateGeometry()

    def set_preview_queue(self, duration_ms: int) -> None:
        self.preview_transport.set_duration(duration_ms)
        self.preview_transport.set_position(0, duration_ms)

    def set_preview_position(self, position_ms: int, duration_ms: int) -> None:
        self.preview_transport.set_position(position_ms, duration_ms)

    def set_preview_playing(self, is_playing: bool) -> None:
        self.preview_transport.set_playing(is_playing)

    def clear_preview(self) -> None:
        self.preview_transport.clear()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = True
        self._sync_action_visibility()
        self.share_action.set_actions_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = False
        self._sync_action_visibility()
        self.share_action.set_actions_expanded(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.can_preview
            and not self._is_editing
        ):
            self.preview_requested.emit(self.path)
        super().mouseReleaseEvent(event)

    def _sync_action_visibility(self) -> None:
        show_row_actions = self._is_hovered or self._is_editing
        self.rename_button.setVisible(show_row_actions)
        self.remove_button.setVisible(show_row_actions)

    def _begin_rename(self) -> None:
        self._is_editing = True
        self.name_edit.setText(self.path.stem)
        self.name_label.hide()
        self.name_edit.show()
        self._sync_action_visibility()
        self.name_edit.setFocus(Qt.FocusReason.MouseFocusReason)
        self.name_edit.selectAll()

    def _commit_rename(self) -> None:
        if not self._is_editing:
            return
        self._is_editing = False
        next_name = self.name_edit.text().strip()
        self.name_edit.hide()
        self.name_label.show()
        self._sync_action_visibility()
        if next_name and next_name != self.path.stem:
            self.rename_requested.emit(self.path, next_name)


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
