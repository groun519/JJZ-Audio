from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, Qt, QTimer
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import (
    APP_ICON_PATH,
    APP_NAME,
    APP_PATHS,
    LOG_FILE,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)
from jang_app.pipeline.rvc_convert import convert_vocal_with_rvc, list_index_files, list_voice_models
from jang_app.pipeline.separate import SeparationResult, separate_audio
from jang_app.qt_app.export_page import ExportPage
from jang_app.qt_app.floating_playback_panel import FloatingPlaybackPanel, floating_player_position
from jang_app.qt_app.library_details_panel import LibraryDetailsPanel
from jang_app.qt_app.library_row import SongListRow
from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog
from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_placeholder,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.log_drawer import LogDrawer
from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.qt_app.processing_queue_panel import ProcessingQueuePanel
from jang_app.qt_app.primary_navigation import PrimaryNavigationBar
from jang_app.qt_app.segmented_stack import SegmentedStack
from jang_app.qt_app.studio_session_autosave import StudioSessionAutosave
from jang_app.qt_app.theme import build_stylesheet, next_theme_mode
from jang_app.qt_app.toast_stack import ToastStack
from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.video_preview_panel import VideoPreviewPanel
from jang_app.qt_app.window_chrome import apply_window_corner_style
from jang_app.qt_app.workspace_transport_dock import WorkspaceTransportDock
from jang_app.qt_app.widgets import (
    FileDropCard,
    FeedbackButton,
    ScrollSafeComboBox,
    ScrollSafeSpinBox,
    SvgIconButton,
    TaskActionWidget,
    ThemeToggleButton,
    TrackRow,
    UrlDownloadCard,
    WindowTitleBar,
    make_list_item,
)
from jang_app.qt_app.workers import TaskProgressTarget, TaskWorker
from jang_app.services.audio_export import export_audio_file
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.audio_player import AudioPlaybackError, AudioPlayer
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.file_browser import open_in_file_browser
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language, tr
from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set, scan_output_sound_sets
from jang_app.services.playback_queue import PlaybackQueue
from jang_app.services.processing_queue import ProcessingQueue
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.settings import AppSettings, RvcSettings, save_app_settings
from jang_app.services.song_metadata import build_song_display_metadata
from jang_app.services.work_scope import WorkTaskScope, build_work_song_capabilities
from jang_app.services.work_song import WorkSongStore
from jang_app.services.video_source import VideoSource
from jang_app.services.song_library import SongItem, SongLibrary, SongVocalVersion, sort_song_items
from jang_app.services.studio_session import StudioSession, StudioTrackState
from jang_app.services.youtube_download import YouTubeDownloadResult, download_youtube_audio


PAGE_LIBRARY = 0
PAGE_MODELS = 1
PAGE_VOCAL = 2
PAGE_STUDIO = 3
PAGE_EXPORT = 4


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, work_song_store: WorkSongStore | None = None) -> None:
        super().__init__()
        self.settings = settings
        set_language(settings.language)
        self.library = SongLibrary()
        self.work_song_store = work_song_store or WorkSongStore()
        self._work_song_ready = False
        self.player = AudioPlayer()
        self.processing_queue = ProcessingQueue()
        self._workers: list[TaskWorker] = []
        self._action_task_ids: dict[int, str] = {}
        self._song_items_by_id: dict[str, SongItem] = {}
        self.current_song: SongItem | None = None
        self.current_work_item: SongItem | None = None
        self.current_output_set: OutputSoundSet | None = None
        self.current_playback_queue: PlaybackQueue | None = None
        self._playback_position_ms = 0
        self._playback_resume_positions: dict[tuple[str, str], int] = {}
        self._library_preview_song_id = ""
        self._export_song_id = ""
        self._is_loading_rvc_settings = False
        self._is_loading_studio_session = False
        self.studio_session_autosave = StudioSessionAutosave(self.library.save_studio_session, parent=self)
        self.studio_session_autosave.save_failed.connect(self._on_studio_session_save_failed)

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setMinimumSize(1180, 760)
        self.resize(1500, 900)

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(120)
        self.playback_timer.timeout.connect(self._sync_global_playback_state)

        self._build_ui()
        self._apply_theme()
        self._apply_language()
        self._refresh_song_list()
        self._refresh_rvc_choices()
        self._refresh_output_sets()
        self._restore_work_song()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.studio_session_autosave.flush()
        self.model_workspace_page.stop_preview()
        self.model_workspace_page.shutdown_training()
        self.player.stop()
        self.video_preview_panel.stop()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_window_chrome_state()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_window_chrome_state()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_floating_playback()
        self._position_processing_queue()
        self._position_size_grip()
        if self.isVisible() and not self.isMaximized():
            apply_window_corner_style(self, rounded=True)

    def _toggle_window_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_window_chrome_state()

    def _sync_window_chrome_state(self) -> None:
        if hasattr(self, "title_bar"):
            self.title_bar.set_maximized(self.isMaximized())
        if hasattr(self, "size_grip"):
            self.size_grip.setVisible(not self.isMaximized())
            self._position_size_grip()
        if self.isVisible():
            apply_window_corner_style(self, rounded=not self.isMaximized())

    def _build_ui(self) -> None:
        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.page_stack = QStackedWidget()
        root_layout.addWidget(self._build_top_bar(), 0)
        navigation_dock = self._build_navigation_bar()
        root_layout.addWidget(navigation_dock, 0)

        self.page_stack.addWidget(self._build_library_page())
        self.page_stack.addWidget(self._build_models_page())
        self.page_stack.addWidget(self._build_vocal_page())
        self.page_stack.addWidget(self._build_studio_page())
        self.page_stack.addWidget(self._build_export_page())

        content_widget = QWidget()
        content_widget.setObjectName("AppContent")
        self._content_widget = content_widget
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(12)
        content_layout.addWidget(self.page_stack, 1)

        self.workspace_dock = WorkspaceTransportDock()
        self.workspace_dock.song_changed.connect(self._on_global_work_song_changed)
        self.workspace_dock.play_toggled.connect(self._toggle_global_playback)
        self.workspace_dock.seek_requested.connect(self._seek_global_playback)
        self.workspace_dock.hide()
        content_layout.addWidget(self.workspace_dock, 0)

        self.floating_playback_panel = FloatingPlaybackPanel(content_widget)
        self.floating_playback_panel.play_toggled.connect(self._toggle_global_playback)
        self.floating_playback_panel.seek_requested.connect(self._seek_global_playback)
        self.floating_playback_panel.dismiss_requested.connect(self._dismiss_floating_playback)
        self.floating_playback_panel.hide()

        self.processing_queue_panel = ProcessingQueuePanel(self.processing_queue, content_widget)
        self.processing_queue_panel.geometry_changed.connect(self._position_processing_queue)
        self.processing_queue_panel.log_requested.connect(self._open_log_drawer)

        self.toast_stack = ToastStack(self.processing_queue, content_widget)
        self.toast_stack.geometry_changed.connect(self._position_processing_queue)
        self.toast_stack.details_requested.connect(self._open_log_drawer)

        self.log_drawer = LogDrawer(self.processing_queue, content_widget)
        self.log_drawer.close_requested.connect(self._close_log_drawer)
        self.log_drawer.open_location_requested.connect(self._open_log_location)
        QTimer.singleShot(0, self._position_floating_playback)
        QTimer.singleShot(0, self._position_processing_queue)

        root_layout.addWidget(content_widget, 1)

        self.setCentralWidget(root_widget)
        self.size_grip = QSizeGrip(root_widget)
        self.size_grip.raise_()
        QTimer.singleShot(0, self._position_size_grip)

    def _build_top_bar(self) -> QWidget:
        self.title_bar = WindowTitleBar(APP_NAME, APP_ICON_PATH)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_window_maximized)
        self.title_bar.close_requested.connect(self.close)
        return self.title_bar

    def _build_navigation_bar(self) -> QWidget:
        self.primary_navigation = PrimaryNavigationBar(
            (
                ("Library", PAGE_LIBRARY),
                ("Models", PAGE_MODELS),
            ),
            (
                ("Vocal", PAGE_VOCAL),
                ("Studio", PAGE_STUDIO),
            ),
            ("Export", PAGE_EXPORT),
        )
        self.primary_navigation.page_requested.connect(self._navigate_to_page)
        self.primary_navigation.settings_requested.connect(self._open_system_setup)

        self.theme_button = ThemeToggleButton()
        self.theme_button.clicked.connect(self._toggle_theme)
        self.language_button = FeedbackButton("KR")
        self.language_button.setObjectName("TitleBarLanguageButton")
        self.language_button.setFixedSize(42, 26)
        self.language_menu = QMenu(self.language_button)
        self.language_action_group = QActionGroup(self.language_menu)
        self.language_action_group.setExclusive(True)
        self.language_actions = {}
        for language, label in ((LANGUAGE_KOREAN, "한국어"), (LANGUAGE_ENGLISH, "English")):
            action = self.language_menu.addAction(label)
            action.setCheckable(True)
            action.setData(language)
            action.triggered.connect(lambda checked, value=language: self._change_language(value) if checked else None)
            self.language_action_group.addAction(action)
            self.language_actions[language] = action
        self.language_button.setMenu(self.language_menu)
        self.settings_button = self.primary_navigation.settings_button
        set_translated_tooltip(self.settings_button, "System setup")
        self.title_bar.add_action_widget(self.language_button)
        self.title_bar.add_action_widget(self.theme_button)

        return self.primary_navigation

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        import_panel = QFrame()
        import_panel.setObjectName("Panel")
        import_panel.setMinimumWidth(360)
        import_panel.setMaximumWidth(430)
        import_layout = QVBoxLayout(import_panel)
        import_layout.setContentsMargins(20, 20, 20, 20)
        import_layout.setSpacing(16)

        heading = QLabel("Import")
        heading.setObjectName("SectionTitle")

        self.library_status_label = QLabel("")
        self.library_status_label.setObjectName("MutedText")
        self.library_status_label.setWordWrap(True)
        self.library_status_label.hide()

        heading_layout = QVBoxLayout()
        heading_layout.setSpacing(8)
        heading_layout.addWidget(heading)
        heading_layout.addWidget(self.library_status_label)

        self.youtube_card = UrlDownloadCard()
        self.youtube_card.download_requested.connect(self._start_youtube_download)

        self.drop_card = FileDropCard()
        self.drop_card.browse_requested.connect(self._choose_audio_files)
        self.drop_card.files_dropped.connect(self._add_songs)

        import_layout.addLayout(heading_layout)
        import_layout.addWidget(self.youtube_card, 0)
        import_layout.addWidget(self.drop_card, 0)
        import_layout.addStretch(1)

        list_panel = QFrame()
        list_panel.setObjectName("Panel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(22, 22, 22, 22)
        list_layout.setSpacing(16)

        list_header = QHBoxLayout()
        list_title = QLabel("Library")
        list_title.setObjectName("SectionTitle")
        self.library_count_label = QLabel("")
        self.library_count_label.setObjectName("MutedText")
        list_header.addWidget(list_title, 0)
        list_header.addWidget(self.library_count_label, 1)

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self.library_search_edit = QLineEdit()
        set_translated_placeholder(self.library_search_edit, "Search songs")
        self.library_search_edit.textChanged.connect(self._apply_library_filters)
        self.library_source_filter = ScrollSafeComboBox()
        self.library_source_filter.setFixedWidth(150)
        self.library_source_filter.currentIndexChanged.connect(self._apply_library_filters)
        self.library_sort_combo = ScrollSafeComboBox()
        self.library_sort_combo.setFixedWidth(150)
        set_translated_tooltip(self.library_sort_combo, "Sort songs")
        self.library_sort_combo.currentIndexChanged.connect(lambda _index: self._refresh_song_list())
        filter_layout.addWidget(self.library_search_edit, 1)
        filter_layout.addWidget(self.library_source_filter, 0)
        filter_layout.addWidget(self.library_sort_combo, 0)

        self.song_list = QListWidget()
        self.song_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.song_list.currentItemChanged.connect(self._on_library_selection_changed)
        self.song_list.itemDoubleClicked.connect(lambda _item: self._open_selected_library_details())

        list_layout.addLayout(list_header)
        list_layout.addLayout(filter_layout)
        list_layout.addWidget(self.song_list, 1)

        self.library_details_panel = LibraryDetailsPanel()
        self.library_details_panel.back_requested.connect(self._close_library_details)
        self.library_details_panel.open_location_requested.connect(self._open_library_asset_location)
        self.library_details_panel.open_vocal_requested.connect(self._use_library_item)

        self.library_content_stack = QStackedWidget()
        self.library_content_stack.addWidget(list_panel)
        self.library_content_stack.addWidget(self.library_details_panel)
        self._populate_library_source_filter()
        self._populate_library_sort_combo()

        layout.addWidget(import_panel, 1)
        layout.addWidget(self.library_content_stack, 3)
        return page

    def _build_vocal_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(380)
        left_panel.setMaximumWidth(460)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(16)

        self.vocal_steps = SegmentedStack(
            (
                ("Separate", self._build_separate_step_page()),
                ("Convert", self._build_convert_step_page()),
            )
        )

        left_layout.addWidget(self.vocal_steps, 1)

        self.vocal_results_panel = VocalResultsPanel()
        self.vocal_results_panel.converted_selected.connect(self._activate_vocal_converted_version)
        self.vocal_results_panel.open_location_requested.connect(self._open_vocal_output_location)
        self.vocal_results_panel.seek_requested.connect(self._seek_output_playback)

        layout.addWidget(left_panel, 0)
        layout.addWidget(self.vocal_results_panel, 1)
        return page

    def _build_studio_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self.video_preview_panel = VideoPreviewPanel()
        self.video_preview_panel.browse_requested.connect(self._choose_video_file)
        self.video_preview_panel.files_dropped.connect(self._attach_video_files)
        self.video_preview_panel.url_requested.connect(self._attach_video_url)
        self.video_preview_panel.open_location_requested.connect(self._open_video_location)
        self.video_preview_panel.clear_requested.connect(self._clear_video_source)
        self.video_preview_panel.download_requested.connect(self._start_video_download)
        self.studio_output_panel = self._build_output_panel()
        self.video_preview_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.studio_output_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )

        layout.addWidget(self.video_preview_panel, 5)
        layout.addWidget(self.studio_output_panel, 7)
        return page

    def _build_export_page(self) -> QWidget:
        self.export_page = ExportPage()
        self.export_page.song_changed.connect(self._on_export_song_changed)
        self.export_page.audio_export_requested.connect(self._start_audio_mix_export)
        self.export_page.video_export_requested.connect(self._start_video_render)
        self.export_page.open_location_requested.connect(self._open_export_location)
        return self.export_page

    def _build_models_page(self) -> QWidget:
        self.model_workspace_page = ModelWorkspacePage(
            self.settings.rvc.root,
            processing_queue=self.processing_queue,
        )
        self.model_workspace_page.use_in_convert_requested.connect(self._use_model_in_convert)
        self.model_workspace_page.open_location_requested.connect(self._open_model_location)
        self.model_workspace_page.preview_started.connect(self._on_model_preview_started)
        return self.model_workspace_page

    def _build_separate_step_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("Card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel("Separate")
        title.setObjectName("SectionTitle")

        self.separation_action = TaskActionWidget("Separation", "Separate")
        self.separation_action.triggered.connect(self._start_separation)
        self.separation_action.set_action_enabled(False)

        layout.addWidget(title)
        layout.addWidget(self.separation_action)
        layout.addStretch(1)
        return page

    def _build_convert_step_page(self) -> QWidget:
        rvc_panel = QFrame()
        rvc_panel.setObjectName("Card")
        rvc_layout = QVBoxLayout(rvc_panel)
        rvc_layout.setContentsMargins(22, 22, 22, 22)
        rvc_layout.setSpacing(16)
        rvc_title = QLabel("RVC Convert")
        rvc_title.setObjectName("SectionTitle")

        self.rvc_settings_frame = QFrame()
        self.rvc_settings_frame.setObjectName("InsetCard")
        form = QGridLayout(self.rvc_settings_frame)
        form.setContentsMargins(14, 14, 14, 14)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(12)

        self.rvc_root_edit = QLineEdit(str(self.settings.rvc.root))
        self.rvc_root_edit.editingFinished.connect(self._save_rvc_settings_from_controls)
        self.browse_rvc_button = SvgIconButton("folder", size=34)
        self.browse_rvc_button.setObjectName("ControlIconButton")
        self.browse_rvc_button.setToolTip("Select RVC root")
        self.browse_rvc_button.clicked.connect(self._choose_rvc_root)

        self.model_combo = ScrollSafeComboBox()
        self.model_combo.currentIndexChanged.connect(self._save_rvc_settings_from_controls)
        self.index_combo = ScrollSafeComboBox()
        self.index_combo.currentIndexChanged.connect(self._save_rvc_settings_from_controls)
        self.refresh_rvc_button = SvgIconButton("refresh", size=34)
        self.refresh_rvc_button.setObjectName("ControlIconButton")
        self.refresh_rvc_button.setToolTip("Refresh RVC models")
        self.refresh_rvc_button.clicked.connect(self._refresh_rvc_choices)

        self.pitch_spin = ScrollSafeSpinBox()
        self.pitch_spin.setRange(-999, 999)
        self.pitch_spin.setValue(self.settings.rvc.pitch)
        self.pitch_spin.valueChanged.connect(self._save_rvc_settings_from_controls)

        self.device_combo = ScrollSafeComboBox()
        self.device_combo.addItems(["cuda:0", "cpu"])
        selected_device = self.settings.rvc.device if self.settings.rvc.device in {"cuda:0", "cpu"} else "cuda:0"
        self.device_combo.setCurrentText(selected_device)
        self.device_combo.currentIndexChanged.connect(self._save_rvc_settings_from_controls)

        form.addWidget(_field_label("Root"), 0, 0)
        form.addWidget(self.rvc_root_edit, 0, 1)
        form.addWidget(self.browse_rvc_button, 0, 2)
        form.addWidget(_field_label("Model"), 1, 0)
        form.addWidget(self.model_combo, 1, 1)
        form.addWidget(self.refresh_rvc_button, 1, 2)
        form.addWidget(_field_label("Index"), 2, 0)
        form.addWidget(self.index_combo, 2, 1, 1, 2)
        form.addWidget(_field_label("Pitch"), 3, 0)
        form.addWidget(self.pitch_spin, 3, 1)
        form.addWidget(_field_label("Device"), 4, 0)
        form.addWidget(self.device_combo, 4, 1)

        self.rvc_action = TaskActionWidget("Convert Vocal", "Convert")
        self.rvc_action.triggered.connect(self._start_rvc_conversion)
        self.rvc_action.set_action_enabled(False)

        rvc_layout.addWidget(rvc_title)
        rvc_layout.addWidget(self.rvc_settings_frame)
        rvc_layout.addWidget(self.rvc_action)
        rvc_layout.addStretch(1)
        return rvc_panel

    def _build_output_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 20, 20, 20)
        panel_layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Output Sounds")
        title.setObjectName("SectionTitle")
        self.output_set_combo = ScrollSafeComboBox()
        self.output_set_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.output_set_combo.currentIndexChanged.connect(self._on_output_set_changed)
        self.output_refresh_button = SvgIconButton("refresh", size=34)
        self.output_refresh_button.setObjectName("ControlIconButton")
        self.output_refresh_button.setToolTip("Refresh output sounds")
        self.output_refresh_button.clicked.connect(lambda: self._refresh_output_sets())
        header.addWidget(title, 0)
        header.addWidget(self.output_set_combo, 1)
        header.addWidget(self.output_refresh_button, 0)

        self.output_status_label = QLabel("")
        self.output_status_label.setObjectName("MutedText")
        self.output_status_label.setWordWrap(True)
        self.output_status_label.hide()

        track_scroll = QScrollArea()
        track_scroll.setWidgetResizable(True)
        track_content = QWidget()
        track_layout = QVBoxLayout(track_content)
        track_layout.setContentsMargins(0, 0, 0, 0)
        track_layout.setSpacing(10)

        self.vocal_track = TrackRow("Original Vocal")
        self.instrumental_track = TrackRow("Instrumental")
        self.converted_track = TrackRow("Converted Vocal", allow_selection=True)
        self.output_tracks = [self.vocal_track, self.instrumental_track, self.converted_track]
        for track in self.output_tracks:
            track.export_requested.connect(self._export_track)
            track.open_location_requested.connect(self._open_track_location)
            track.seek_requested.connect(self._seek_output_playback)
            track.playback_settings_changed.connect(self._on_output_playback_settings_changed)
            track.source_changed.connect(self._on_output_track_source_changed)
            track_layout.addWidget(track)
        track_layout.addStretch(1)
        track_scroll.setWidget(track_content)

        panel_layout.addLayout(header)
        panel_layout.addWidget(self.output_status_label, 0)
        panel_layout.addWidget(track_scroll, 1)
        return panel

    def _apply_theme(self) -> None:
        self.setStyleSheet(build_stylesheet(self.settings.theme_mode))
        self.title_bar.set_theme_mode(self.settings.theme_mode)
        self.primary_navigation.set_theme_mode(self.settings.theme_mode)
        self.theme_button.set_theme_mode(self.settings.theme_mode)
        self.settings_button.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "workspace_dock"):
            self.workspace_dock.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "floating_playback_panel"):
            self.floating_playback_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "processing_queue_panel"):
            self.processing_queue_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "toast_stack"):
            self.toast_stack.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "log_drawer"):
            self.log_drawer.set_theme_mode(self.settings.theme_mode)
        for button_name in ("output_refresh_button", "browse_rvc_button", "refresh_rvc_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "drop_card"):
            self.drop_card.file_button.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "model_workspace_page"):
            self.model_workspace_page.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "vocal_results_panel"):
            self.vocal_results_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "library_details_panel"):
            self.library_details_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "export_page"):
            self.export_page.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "video_preview_panel"):
            self.video_preview_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "song_list"):
            for index in range(self.song_list.count()):
                row = self.song_list.itemWidget(self.song_list.item(index))
                if hasattr(row, "set_theme_mode"):
                    row.set_theme_mode(self.settings.theme_mode)
        for track in getattr(self, "output_tracks", []):
            track.set_theme_mode(self.settings.theme_mode)

    def _apply_language(self) -> None:
        set_language(self.settings.language)
        apply_widget_language(self)
        self.language_button.setText("KR" if self.settings.language == LANGUAGE_KOREAN else "EN")
        set_translated_tooltip(self.language_button, "Language")
        for language, action in self.language_actions.items():
            action.setChecked(language == self.settings.language)
        self.workspace_dock.apply_language()
        self.floating_playback_panel.apply_language()
        self.processing_queue_panel.apply_language()
        self.toast_stack.apply_language()
        self.log_drawer.apply_language()
        self.model_workspace_page.apply_language()
        self.vocal_results_panel.apply_language()
        self.library_details_panel.apply_language()
        self.export_page.apply_language()
        self.video_preview_panel.apply_language()
        self._populate_library_source_filter()
        self._populate_library_sort_combo()
        set_translated_tooltip(self.library_sort_combo, "Sort songs")

    def _position_floating_playback(self) -> None:
        if not hasattr(self, "floating_playback_panel") or not hasattr(self, "workspace_dock"):
            return
        panel = self.floating_playback_panel
        if not panel.isVisible():
            return
        parent = self._content_widget
        anchor_top = (
            self.workspace_dock.geometry().top() if self.workspace_dock.isVisible() else None
        )
        panel.move(
            *floating_player_position(
                parent.height(),
                panel.height(),
                anchor_top=anchor_top,
            )
        )
        panel.raise_()

    def _sync_playback_surfaces(self) -> None:
        if not hasattr(self, "floating_playback_panel") or not hasattr(self, "workspace_dock"):
            return
        page_index = self.page_stack.currentIndex()
        is_workspace_page = page_index in {PAGE_VOCAL, PAGE_STUDIO}
        queue = self.current_playback_queue
        self.workspace_dock.setVisible(is_workspace_page)
        self.floating_playback_panel.setVisible(
            queue is not None and (not is_workspace_page or queue.context == "library")
        )
        self._position_floating_playback()
        self._position_processing_queue()

    def _position_processing_queue(self) -> None:
        if not hasattr(self, "processing_queue_panel") or not hasattr(self, "workspace_dock"):
            return
        panel = self.processing_queue_panel
        parent = self._content_widget
        player_top = self.workspace_dock.geometry().top() if self.workspace_dock.isVisible() else parent.height() - 16
        drawer_open = hasattr(self, "log_drawer") and self.log_drawer.isVisible()

        if drawer_open:
            drawer = self.log_drawer
            top_position = 16
            drawer.setFixedHeight(max(260, player_top - top_position - 10))
            drawer.move(max(16, parent.width() - drawer.width() - 16), top_position)
            drawer.raise_()
            panel.hide()
        elif panel.has_tasks():
            panel.show()
            x_position = max(16, parent.width() - panel.width() - 16)
            y_position = max(16, player_top - panel.height() - 10)
            panel.move(x_position, y_position)
            panel.raise_()
        else:
            panel.hide()

        if hasattr(self, "toast_stack") and self.toast_stack.isVisible():
            toast = self.toast_stack
            if drawer_open:
                toast_x = max(16, self.log_drawer.x() - toast.width() - 10)
                toast_y = max(16, player_top - toast.height() - 10)
            else:
                toast_x = max(16, parent.width() - toast.width() - 16)
                toast_anchor = panel.y() if panel.isVisible() else player_top
                toast_y = max(16, toast_anchor - toast.height() - 10)
            toast.move(toast_x, toast_y)
            toast.raise_()

    def _position_size_grip(self) -> None:
        if not hasattr(self, "size_grip"):
            return
        parent = self.size_grip.parentWidget()
        if parent is None:
            return
        self.size_grip.resize(self.size_grip.sizeHint())
        self.size_grip.move(
            max(0, parent.width() - self.size_grip.width()),
            max(0, parent.height() - self.size_grip.height()),
        )
        self.size_grip.raise_()

    def _open_log_drawer(self, task_id: str = "") -> None:
        self.toast_stack.dismiss_all()
        self.log_drawer.show()
        self.log_drawer.refresh_content()
        if task_id:
            self.log_drawer.select_task(task_id)
        self._position_processing_queue()

    def _close_log_drawer(self) -> None:
        self.log_drawer.hide()
        self.processing_queue_panel.show()
        self._position_processing_queue()

    def _open_log_location(self, path: Path) -> None:
        target = path if path.exists() else path.parent
        try:
            open_in_file_browser(target)
        except Exception as exc:
            self.log_drawer.application_log.setPlainText(f"Open failed: {_last_error_line(str(exc))}")

    def _toggle_theme(self, *_args) -> None:
        self.settings = replace(self.settings, theme_mode=next_theme_mode(self.settings.theme_mode))
        save_app_settings(self.settings)
        self._apply_theme()

    def _open_system_setup(self) -> None:
        dialog = InitialSetupDialog(
            APP_PATHS,
            APP_ICON_PATH,
            first_run=False,
            theme_mode=self.settings.theme_mode,
        )
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.restart_required:
            return
        if getattr(sys, "frozen", False):
            arguments = sys.argv[1:]
        else:
            arguments = [str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
        if QProcess.startDetached(sys.executable, arguments, str(Path.cwd())):
            QApplication.quit()

    def _change_language(self, language: str) -> None:
        if language == self.settings.language:
            return
        self.settings = replace(self.settings, language=language)
        save_app_settings(self.settings)
        self._apply_language()

    def _navigate_to_page(self, index: int) -> None:
        previous_index = self.page_stack.currentIndex()
        if previous_index == PAGE_STUDIO and index != PAGE_STUDIO:
            self.studio_session_autosave.flush()
        if index != PAGE_MODELS:
            self.model_workspace_page.stop_preview()
        self.page_stack.setCurrentIndex(index)
        self.primary_navigation.set_current_page(index)
        if index == PAGE_EXPORT:
            self._refresh_export_page()
        self._sync_playback_queue_for_page(index)
        self._sync_playback_surfaces()
        self._sync_video_workspace()
        QTimer.singleShot(0, self._sync_playback_surfaces)

    def _navigate_to_vocal_step(self, index: int) -> None:
        self.vocal_steps.set_current_index(index)

    def _choose_audio_files(self, *_args) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_AUDIO_EXTENSIONS))
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            tr("Select Audio Files"),
            str(Path.home()),
            f"{tr('Audio Files')} ({suffixes})",
        )
        if filenames:
            self._add_songs([Path(filename) for filename in filenames])

    def _choose_video_file(self, *_args) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_VIDEO_EXTENSIONS))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select Video"),
            str(Path.home()),
            f"{tr('Video Files')} ({suffixes})",
        )
        if not filename:
            return
        self._start_video_file_import(Path(filename))

    def _attach_video_files(self, paths: object) -> None:
        candidates = [
            Path(path)
            for path in paths
            if Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        ] if isinstance(paths, (list, tuple)) else []
        if not candidates:
            self.video_preview_panel.set_status("Select a supported video file.")
            return
        self._start_video_file_import(candidates[0])

    def _start_video_file_import(self, source: Path) -> None:
        item = self.current_work_item
        if item is None:
            self.video_preview_panel.set_status("Select a song.")
            return
        scope = WorkTaskScope(item.id)
        source = source.expanduser().resolve()
        self.video_preview_panel.set_running(True)
        self.video_preview_panel.set_progress(1)
        self.video_preview_panel.set_status("Importing video")
        worker = TaskWorker(lambda progress: self.library.set_video_file(scope.song_id, source, progress))
        self._run_worker(
            worker,
            lambda result: self._on_video_source_attached(scope, result),
            lambda error: self._on_video_source_failed(scope, error),
            self.video_preview_panel,
            task_title="Import Video",
            task_detail=source.name,
            action_scope=lambda: scope.is_current(self.current_work_item),
        )

    def _attach_video_url(self, url: str) -> None:
        item = self.current_work_item
        if item is None:
            self.video_preview_panel.set_status("Select a song.")
            return
        try:
            source = self.library.set_video_url(item.id, url)
        except (KeyError, ValueError) as exc:
            self.video_preview_panel.set_status(str(exc))
            return
        self._set_video_source(source, enabled=True)
        self.video_preview_panel.set_status("Video attached")
        self._refresh_open_library_details(item.id)

    def _start_video_download(self) -> None:
        item = self.current_work_item
        if item is None:
            self.video_preview_panel.set_status("Select a song.")
            return
        scope = WorkTaskScope(item.id)
        self.video_preview_panel.set_running(True)
        self.video_preview_panel.set_progress(1)
        self.video_preview_panel.set_status("Downloading video")
        worker = TaskWorker(lambda progress: self.library.download_video_source(scope.song_id, progress))
        self._run_worker(
            worker,
            lambda result: self._on_video_downloaded(scope, result),
            lambda error: self._on_video_source_failed(scope, error),
            self.video_preview_panel,
            task_title="Download Video",
            task_detail=item.title,
            action_scope=lambda: scope.is_current(self.current_work_item),
        )

    def _clear_video_source(self) -> None:
        item = self.current_work_item
        if item is None:
            return
        try:
            source = self.library.clear_video_source(item.id)
        except KeyError:
            return
        self._set_video_source(source, enabled=True)
        self.video_preview_panel.set_status("Video source cleared")
        self._refresh_open_library_details(item.id)

    def _on_video_source_attached(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_open_library_details(scope.song_id)
        if not scope.is_current(self.current_work_item) or not isinstance(result, VideoSource):
            return
        self._set_video_source(result, enabled=True)
        self.video_preview_panel.set_status("Video attached")

    def _on_video_downloaded(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_open_library_details(scope.song_id)
        if not scope.is_current(self.current_work_item) or not isinstance(result, VideoSource):
            return
        self._set_video_source(result, enabled=True)
        self.video_preview_panel.set_progress(100)
        self.video_preview_panel.set_status("Video downloaded")

    def _on_video_source_failed(self, scope: WorkTaskScope, error: str) -> None:
        if scope.is_current(self.current_work_item):
            self.video_preview_panel.set_status(f"Video failed: {_last_error_line(error)}", error)

    def _open_video_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            self.video_preview_panel.set_status(f"Open failed: {_last_error_line(str(exc))}")

    def _start_video_render(self, song_id: str) -> None:
        item = self._song_items_by_id.get(song_id)
        if item is None:
            self.export_page.set_video_status("Select a song.")
            return
        self._queue_current_studio_session_save()
        self.studio_session_autosave.flush()
        scope = WorkTaskScope(item.id)
        self.export_page.set_video_running(True)
        self.export_page.set_video_progress(1)
        self.export_page.set_video_status("Rendering video")
        worker = TaskWorker(lambda progress: self.library.render_video(scope.song_id, progress))
        self._run_worker(
            worker,
            lambda result: self._on_video_rendered(scope, result),
            lambda error: self._on_video_render_failed(scope, error),
            self.export_page.video_action,
            task_title="Render Video",
            task_detail=item.title,
            action_scope=lambda: self._is_export_song(scope.song_id),
        )

    def _on_video_rendered(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_open_library_details(scope.song_id)
        self._refresh_export_page()
        if not self._is_export_song(scope.song_id):
            return
        path = result if isinstance(result, Path) else None
        self.export_page.set_video_progress(100)
        self.export_page.set_video_status("Video rendered", str(path) if path is not None else "")

    def _on_video_render_failed(self, scope: WorkTaskScope, error: str) -> None:
        if not self._is_export_song(scope.song_id):
            return
        self.export_page.set_video_status(f"Render failed: {_last_error_line(error)}", error)

    def _refresh_open_library_details(self, song_id: str) -> None:
        if self.library_content_stack.currentIndex() == 1 and self.library_details_panel.song_id == song_id:
            self._open_library_details(song_id)

    def _add_songs(self, paths: list[Path]) -> None:
        added = self.library.add_paths(paths)
        self._refresh_song_list()
        if not added:
            _set_optional_label(self.library_status_label, "Unsupported file.")
            return

        _set_optional_label(self.library_status_label, f"Added {len(added)}")
        self._select_library_song(added[0].id)

    def _start_youtube_download(self, url: str) -> None:
        if not url:
            self.youtube_card.set_status("URL required.")
            return

        self._stop_playback()
        self.youtube_card.set_running(True)
        self.youtube_card.set_progress(2)
        self.youtube_card.set_status("Downloading")
        worker = TaskWorker(lambda progress: download_youtube_audio(url, progress_callback=progress))
        self._run_worker(
            worker,
            self._on_youtube_download_succeeded,
            self._on_youtube_download_failed,
            self.youtube_card,
            task_title="Download Audio",
            task_detail=url,
        )

    def _on_youtube_download_succeeded(self, result: object) -> None:
        download_result = result if isinstance(result, YouTubeDownloadResult) else None
        if download_result is None:
            self.youtube_card.set_status("Failed")
            return

        song = self.library.add_youtube_audio(
            download_result.audio_path,
            download_result.title,
            download_result.url,
        )
        self._refresh_song_list()
        if song is not None:
            self._select_library_song(song.id)
        self.youtube_card.url_edit.clear()
        self.youtube_card.set_progress(100)
        self.youtube_card.set_status("Done")
        _set_optional_label(self.library_status_label, f"Downloaded: {download_result.title}")

    def _on_youtube_download_failed(self, error: str) -> None:
        self.youtube_card.set_status("Failed")
        self.youtube_card.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

    def _refresh_song_list(self) -> None:
        selected_id = self._browsed_song_id()
        detail_song_id = self.library_details_panel.song_id
        detail_is_open = self.library_content_stack.currentIndex() == 1
        work_item_id = self.current_work_item.id if self.current_work_item is not None else ""
        self.song_list.blockSignals(True)
        self.song_list.clear()
        items = self.library.items()
        self._song_items_by_id = {item.id: item for item in items}
        if self._library_preview_song_id not in self._song_items_by_id:
            if self._current_playback_context() == "library":
                self._stop_playback(clear_queue=True)
            self._library_preview_song_id = ""
        self.current_work_item = self._song_items_by_id.get(work_item_id)
        self.current_song = (
            self.current_work_item
            if self.current_work_item is not None and self.current_work_item.kind == "source"
            else None
        )
        sort_mode = str(self.library_sort_combo.currentData() or "newest")
        for item in sort_song_items(items, sort_mode):
            metadata = build_song_display_metadata(item, self.settings.output_root)
            row = SongListRow(item.id, item.title, metadata)
            row.set_theme_mode(self.settings.theme_mode)
            apply_widget_language(row)
            row.use_requested.connect(self._use_library_item)
            row.details_requested.connect(self._open_library_details)
            row.rename_requested.connect(self._rename_library_item)
            row.remove_requested.connect(self._remove_library_item)
            row.preview_requested.connect(self._select_library_preview)
            list_item = make_list_item(row)
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self.song_list.addItem(list_item)
            self.song_list.setItemWidget(list_item, row)
        self.song_list.blockSignals(False)
        if selected_id and self._select_library_song(selected_id):
            pass
        elif self.song_list.count() > 0:
            self.song_list.setCurrentRow(0)
        else:
            self._on_library_selection_changed()
        self._sync_song_row_selection()
        self._apply_library_filters()
        self._refresh_work_song_selector()
        self._refresh_export_page()
        if self._current_playback_context() == "library":
            self._refresh_playback_ui(is_playing=self.player.is_playing())
        if detail_is_open and detail_song_id in self._song_items_by_id:
            self._open_library_details(detail_song_id)
        elif detail_is_open:
            self._close_library_details()

    def _select_library_song(self, song_id: str) -> bool:
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == song_id:
                self.song_list.setCurrentItem(item)
                return True
        return False

    def _on_library_selection_changed(self, *_args) -> None:
        self._sync_song_row_selection()

    def _select_library_preview(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            self._library_preview_song_id = ""
            return
        self._select_library_song(song_id)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "library" and queue.source_id == song_id:
            self._library_preview_song_id = song_id
            self._sync_playback_surfaces()
            return
        self._library_preview_song_id = song_id
        self._load_library_playback_queue(song)

    def _populate_library_source_filter(self) -> None:
        current = self.library_source_filter.currentData() if self.library_source_filter.count() else "all"
        self.library_source_filter.blockSignals(True)
        self.library_source_filter.clear()
        for label, value in (
            ("All Sources", "all"),
            ("LOCAL", "local"),
            ("YOUTUBE", "youtube"),
            ("OUTPUT", "output"),
        ):
            self.library_source_filter.addItem(tr(label), value)
        index = self.library_source_filter.findData(current)
        self.library_source_filter.setCurrentIndex(index if index >= 0 else 0)
        self.library_source_filter.blockSignals(False)

    def _populate_library_sort_combo(self) -> None:
        current = self.library_sort_combo.currentData() if self.library_sort_combo.count() else "newest"
        self.library_sort_combo.blockSignals(True)
        self.library_sort_combo.clear()
        for label, value in (
            ("Newest", "newest"),
            ("Oldest", "oldest"),
            ("Name A-Z", "name_asc"),
            ("Name Z-A", "name_desc"),
        ):
            self.library_sort_combo.addItem(tr(label), value)
        index = self.library_sort_combo.findData(current)
        self.library_sort_combo.setCurrentIndex(index if index >= 0 else 0)
        self.library_sort_combo.blockSignals(False)

    def _apply_library_filters(self, *_args) -> None:
        query = self.library_search_edit.text().strip().casefold()
        source_filter = str(self.library_source_filter.currentData() or "all")
        visible_items = []
        for index in range(self.song_list.count()):
            list_item = self.song_list.item(index)
            song = self._song_items_by_id.get(list_item.data(Qt.ItemDataRole.UserRole))
            is_visible = song is not None and (
                not query or query in song.title.casefold() or query in song.path.name.casefold()
            )
            if is_visible and source_filter != "all":
                is_visible = song.source_type == source_filter
            list_item.setHidden(not is_visible)
            if is_visible:
                visible_items.append(list_item)

        self.library_count_label.setText(f"{len(visible_items)} / {self.song_list.count()}")
        current = self.song_list.currentItem()
        if current is not None and current.isHidden():
            self.song_list.setCurrentItem(visible_items[0] if visible_items else None)
    def _open_selected_library_details(self, *_args) -> None:
        song = self._browsed_song()
        if song is not None:
            self._open_library_details(song.id)

    def _open_library_details(self, song_id: str) -> None:
        try:
            details = self.library.asset_details(song_id)
        except KeyError:
            return
        self.library_details_panel.set_details(details)
        self.library_content_stack.setCurrentWidget(self.library_details_panel)

    def _close_library_details(self) -> None:
        self.library_content_stack.setCurrentIndex(0)

    def _open_library_asset_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            _set_optional_label(self.library_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _sync_song_row_selection(self) -> None:
        selected_id = self._browsed_song_id()
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            row = self.song_list.itemWidget(item)
            if hasattr(row, "set_selected"):
                row.set_selected(item.data(Qt.ItemDataRole.UserRole) == selected_id)

    def _browsed_song(self) -> SongItem | None:
        current_item = self.song_list.currentItem()
        if current_item is None:
            return None
        return self._song_items_by_id.get(current_item.data(Qt.ItemDataRole.UserRole))

    def _browsed_song_id(self) -> str:
        current_item = self.song_list.currentItem()
        return current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else ""

    def _rename_library_item(self, song_id: str, new_title: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            return

        if not self.library.rename_item(song_id, new_title):
            _set_optional_label(self.library_status_label, "Name required.")
            return

        queue = self.current_playback_queue
        if queue is not None and queue.context == "library" and queue.source_id == song_id:
            self.current_playback_queue = replace(queue, title=new_title)
        _set_optional_label(self.library_status_label, "Renamed")
        self._refresh_song_list()
        self._select_library_song(song_id)
        if self.current_work_item is not None and self.current_work_item.id == song_id:
            self._assign_work_item(self._song_items_by_id.get(song_id), persist=False)

    def _remove_library_item(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            return

        was_current_song = self.current_song is not None and self.current_song.id == song_id
        was_work_item = self.current_work_item is not None and self.current_work_item.id == song_id
        is_previewing_song = (
            self._current_playback_context() == "library"
            and self.current_playback_queue is not None
            and self.current_playback_queue.source_id == song_id
        )
        if is_previewing_song:
            self._stop_playback(clear_queue=True)
            self._library_preview_song_id = ""
        self._playback_resume_positions.pop(("library", song_id), None)
        if not self.library.remove_item(song_id):
            return

        if was_current_song or was_work_item:
            self._set_current_song(None)
        _set_optional_label(self.library_status_label, "Removed")
        self._refresh_song_list()

    def _refresh_work_song_selector(self) -> None:
        if not hasattr(self, "workspace_dock"):
            return
        selected_id = self.current_work_item.id if self.current_work_item is not None else ""
        songs = sorted(
            self._song_items_by_id.values(),
            key=lambda item: (item.title.casefold(), item.id),
        )
        self.workspace_dock.set_songs(
            ((song.id, song.title) for song in songs),
            selected_id,
        )
        if selected_id and self.workspace_dock.selected_song_id() != selected_id:
            self._set_current_song(None)

    def _on_global_work_song_changed(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id) if song_id else None
        if song is not None and song.kind == "output":
            self._set_output_work_song(song)
        else:
            self._set_current_song(song)

    def _set_current_song(self, song: SongItem | None, *, persist: bool = True) -> None:
        self._assign_work_item(song, persist=persist)
        if song is None or song.output_job_dir is None:
            self._apply_output_set(None)
            return
        sound_set = load_output_sound_set(song.output_job_dir, self.settings.output_root)
        self._select_output_set(song.output_job_dir)
        self._apply_output_set(sound_set)

    def _set_output_work_song(self, song: SongItem, *, persist: bool = True) -> bool:
        self._assign_work_item(song, persist=persist)
        if song.output_job_dir is None:
            self._apply_output_set(None)
            return False
        sound_set = load_output_sound_set(song.output_job_dir, self.settings.output_root)
        if sound_set is None:
            self._apply_output_set(None)
            return False
        self._select_output_set(sound_set.job_dir)
        self._apply_output_set(sound_set)
        return True

    def _assign_work_item(self, item: SongItem | None, *, persist: bool = True) -> None:
        self.current_work_item = item
        self.current_song = item if item is not None and item.kind == "source" else None
        self.separation_action.set_progress(0)
        self.separation_action.set_status("")
        if hasattr(self, "workspace_dock"):
            selected_id = item.id if item is not None else ""
            if selected_id and not self.workspace_dock.has_song(selected_id):
                self._refresh_work_song_selector()
            else:
                self.workspace_dock.select_song(selected_id)
        if persist and self._work_song_ready:
            try:
                self.work_song_store.save(item.id if item is not None else "")
            except OSError as exc:
                _set_optional_label(self.output_status_label, f"Work song failed: {_last_error_line(str(exc))}")
        self._sync_work_song_capabilities()
        self._refresh_video_source()

    def _sync_work_song_capabilities(self) -> None:
        capabilities = build_work_song_capabilities(
            self.current_work_item,
            output_available=self._current_output_matches_work_song(),
        )
        self.separation_action.set_action_enabled(capabilities.can_separate)
        self.rvc_action.set_action_enabled(capabilities.can_convert)

    def _current_output_matches_work_song(self) -> bool:
        item = self.current_work_item
        sound_set = self.current_output_set
        if item is None or item.output_job_dir is None or sound_set is None:
            return False
        try:
            return item.output_job_dir.expanduser().resolve() == sound_set.job_dir.expanduser().resolve()
        except OSError:
            return False

    def _refresh_video_source(self) -> None:
        item = self.current_work_item
        if item is None:
            self._set_video_source(VideoSource(), enabled=False)
            return
        try:
            source = self.library.video_source(item.id)
        except KeyError:
            source = VideoSource()
        self._set_video_source(source, enabled=True)

    def _set_video_source(self, source: VideoSource, *, enabled: bool) -> None:
        item = self.current_work_item
        original_url = (
            item.source_url
            if item is not None and item.source_type == "youtube"
            else ""
        )
        self.video_preview_panel.set_source(
            source,
            enabled=enabled,
            original_song_url=original_url,
        )
        self._sync_video_workspace()

    def _sync_video_workspace(self) -> None:
        if not hasattr(self, "video_preview_panel"):
            return
        video_active = self.page_stack.currentIndex() == PAGE_STUDIO
        self.video_preview_panel.set_active(video_active)
        self._sync_video_playback(self.player.is_playing())

    def _sync_video_playback(self, is_playing: bool) -> None:
        if not hasattr(self, "video_preview_panel"):
            return
        video_active = self.page_stack.currentIndex() == PAGE_STUDIO
        self.video_preview_panel.sync_playback(
            self._playback_position_ms,
            video_active and is_playing and self._current_playback_context() == "output",
        )

    def _restore_work_song(self) -> None:
        state = self.work_song_store.load()
        item = self._song_items_by_id.get(state.song_id) if state.song_id else None
        if item is not None and item.kind == "output":
            self._set_output_work_song(item, persist=False)
        else:
            self._set_current_song(item, persist=False)
        self._work_song_ready = True
        if state.song_id and item is None:
            try:
                self.work_song_store.save("")
            except OSError:
                pass

    def _select_work_song(self, song: SongItem) -> None:
        if song.kind == "output":
            self._set_output_work_song(song)
        else:
            self._set_current_song(song)

    def _use_library_item(self, song_id: str) -> None:
        if song_id:
            self._select_library_song(song_id)
        song = self._browsed_song()
        if song is None:
            _set_optional_label(self.library_status_label, "Select song.")
            return
        if song.kind == "output":
            self._use_output_song(song)
            return

        self._select_work_song(song)
        _set_optional_label(self.library_status_label, "Loaded")
        self._navigate_to_page(PAGE_VOCAL)
        self._navigate_to_vocal_step(0)

    def _library_playback_queue(self, song: SongItem) -> PlaybackQueue | None:
        try:
            paths = self._song_playback_paths(song)
            duration_ms = self._duration_ms_for_paths(paths)
        except Exception as exc:
            _set_optional_label(self.library_status_label, f"Load failed: {_last_error_line(str(exc))}")
            return None
        if not paths or duration_ms <= 0:
            _set_optional_label(self.library_status_label, "Cannot preview.")
            return None
        return PlaybackQueue(
            context="library",
            source_id=song.id,
            title=song.title,
            paths=tuple(paths),
            volumes=tuple(1.0 for _path in paths),
            duration_ms=duration_ms,
        )

    def _song_playback_paths(self, song: SongItem) -> list[Path]:
        if song.kind != "output":
            return [song.path]
        if song.output_job_dir is None:
            raise AudioPlaybackError("Output item has no job folder.")

        sound_set = load_output_sound_set(song.output_job_dir, self.settings.output_root)
        if sound_set is None:
            raise AudioPlaybackError("Could not load the selected output set.")
        return [sound_set.vocals_path, sound_set.instrumental_path]

    def _load_library_playback_queue(self, song: SongItem | None, *, auto_play: bool = False) -> None:
        if song is None:
            if self._current_playback_context() == "library":
                self._stop_playback(clear_queue=True)
            return
        queue = self._library_playback_queue(song)
        if queue is None:
            return
        self._set_playback_queue(
            queue,
            position_ms=self._resume_position(queue),
            auto_play=auto_play,
        )

    def _start_separation(self, *_args) -> None:
        if self.current_song is None:
            self.separation_action.set_status("Select song.")
            return

        self._stop_playback()
        self.separation_action.set_running(True)
        self.separation_action.set_progress(3)
        self.separation_action.set_status("Separating")
        song = self.current_song
        scope = WorkTaskScope(song.id)
        output_root = self.library.create_vocal_separation_run(song.id)
        worker = TaskWorker(
            lambda progress: separate_audio(
                song.path,
                output_root=output_root,
                progress_callback=progress,
            )
        )
        self._run_worker(
            worker,
            lambda result: self._on_separation_succeeded(scope, result),
            lambda error: self._on_separation_failed(scope, error),
            self.separation_action,
            task_title="Separate Audio",
            task_detail=song.title,
            action_scope=lambda: scope.is_current(self.current_work_item),
        )

    def _on_separation_succeeded(self, scope: WorkTaskScope, result: object) -> None:
        separation_result = result if isinstance(result, SeparationResult) else None
        if separation_result is None:
            if scope.is_current(self.current_work_item):
                self.separation_action.set_status("Failed")
            return

        self.library.register_output(
            scope.song_id,
            separation_result.job_dir,
            separation_result.job_dir.parent.name,
        )
        self._refresh_output_sets_after_task(scope, separation_result.job_dir)
        if scope.is_current(self.current_work_item):
            self.separation_action.set_progress(100)
            self.separation_action.set_status("Done")

    def _on_separation_failed(self, scope: WorkTaskScope, error: str) -> None:
        if not scope.is_current(self.current_work_item):
            return
        self.separation_action.set_status("Failed")
        self.separation_action.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

    def _refresh_output_sets_after_task(self, scope: WorkTaskScope, completed_job_dir: Path) -> None:
        current_output_dir = self.current_output_set.job_dir if self.current_output_set is not None else None
        target = scope.output_refresh_target(
            completed_job_dir,
            self.current_work_item,
            current_output_dir,
        )
        self._refresh_output_sets(
            preferred_job_dir=target.preferred_job_dir,
            select_fallback=target.select_fallback,
        )

    def _refresh_output_sets(
        self,
        preferred_job_dir: Path | None = None,
        *,
        select_fallback: bool = True,
    ) -> None:
        legacy_sound_sets = scan_output_sound_sets(self.settings.output_root)
        self.library.add_output_sets(legacy_sound_sets)
        sound_sets = self.library.output_sound_sets()
        if hasattr(self, "song_list"):
            self._refresh_song_list()

        self.output_set_combo.blockSignals(True)
        self.output_set_combo.clear()
        for sound_set in sound_sets:
            self.output_set_combo.addItem(sound_set.label, str(sound_set.job_dir))

        if not sound_sets:
            self.output_set_combo.blockSignals(False)
            self._apply_output_set(None)
            return

        if preferred_job_dir is None and not select_fallback:
            self.output_set_combo.setCurrentIndex(-1)
            self.output_set_combo.blockSignals(False)
            self._apply_output_set(None)
            return

        preferred_index = 0
        if preferred_job_dir is not None:
            resolved = preferred_job_dir.expanduser().resolve()
            for index, sound_set in enumerate(sound_sets):
                if sound_set.job_dir.expanduser().resolve() == resolved:
                    preferred_index = index
                    break
        self.output_set_combo.setCurrentIndex(preferred_index)
        self.output_set_combo.blockSignals(False)
        self._apply_output_set(sound_sets[preferred_index])

    def _use_output_song(self, song: SongItem) -> None:
        if song.output_job_dir is None:
            _set_optional_label(self.library_status_label, "Missing output.")
            return
        if not self._set_output_work_song(song):
            _set_optional_label(self.library_status_label, "Load failed.")
            return
        _set_optional_label(self.library_status_label, "Loaded")
        self._navigate_to_page(PAGE_STUDIO)

    def _select_output_set(self, job_dir: Path) -> None:
        resolved = job_dir.expanduser().resolve()
        for index in range(self.output_set_combo.count()):
            data = self.output_set_combo.itemData(index)
            if data and Path(data).expanduser().resolve() == resolved:
                was_blocked = self.output_set_combo.blockSignals(True)
                self.output_set_combo.setCurrentIndex(index)
                self.output_set_combo.blockSignals(was_blocked)
                return

    def _on_output_set_changed(self, *_args) -> None:
        data = self.output_set_combo.currentData()
        if not data:
            self._apply_output_set(None)
            return
        self._activate_output_job(Path(data))

    def _activate_output_job(self, job_dir: Path) -> None:
        song = self.library.activate_output(job_dir)
        if song is not None:
            self._song_items_by_id[song.id] = song
            self._assign_work_item(song)
        self._apply_output_set(load_output_sound_set(job_dir, self.settings.output_root))

    def _activate_vocal_converted_version(self, path: Path | None) -> None:
        if self.current_output_set is None:
            return
        song = self.library.activate_converted_output(self.current_output_set.job_dir, path)
        if song is not None:
            self._song_items_by_id[song.id] = song
            if self.current_work_item is not None and self.current_work_item.id == song.id:
                self._assign_work_item(song, persist=False)
        self.converted_track.select_path(path)
        self._refresh_output_playback_queue()

    def _open_vocal_output_location(self, job_dir: Path) -> None:
        try:
            open_in_file_browser(job_dir)
        except Exception as exc:
            _set_optional_label(self.output_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _apply_output_set(self, sound_set: OutputSoundSet | None) -> None:
        self.studio_session_autosave.flush()
        self.current_output_set = sound_set
        self._sync_current_work_output_item(sound_set)
        if sound_set is None:
            self.vocal_track.set_single_path(None)
            self.instrumental_track.set_single_path(None)
            self.converted_track.set_options([])
            self._apply_studio_session(StudioSession())
            self.vocal_results_panel.set_result(None)
            self.rvc_action.set_status("")
            _set_optional_label(self.output_status_label, "")
            self._refresh_output_playback_queue()
            self._sync_work_song_capabilities()
            self._refresh_export_page()
            return

        self.vocal_track.set_single_path(sound_set.vocals_path)
        self.instrumental_track.set_single_path(sound_set.instrumental_path)
        selected_version = self._current_vocal_result(sound_set)
        selected_converted = selected_version.active_converted_path if selected_version is not None else None
        self.converted_track.set_options(list(sound_set.converted_vocal_paths), selected_converted)
        self._restore_current_studio_session()
        self.vocal_results_panel.set_result(selected_version)
        self.rvc_action.set_progress(0)
        self.rvc_action.set_status("")
        _set_optional_label(self.output_status_label, "")
        self._refresh_output_playback_queue()
        self._sync_work_song_capabilities()
        self._refresh_export_page()

    def _current_vocal_result(self, sound_set: OutputSoundSet) -> SongVocalVersion | None:
        item = self.current_song or self.current_work_item
        if item is None:
            return None
        try:
            target = sound_set.job_dir.expanduser().resolve()
            return next(
                (
                    version
                    for version in self.library.vocal_versions(item.id)
                    if version.job_dir.expanduser().resolve() == target
                ),
                None,
            )
        except KeyError:
            return None

    def _sync_current_work_output_item(self, sound_set: OutputSoundSet | None) -> None:
        if self.current_song is not None:
            return
        if sound_set is None:
            return
        item = self._output_item_for_sound_set(sound_set)
        if item is not None:
            self._assign_work_item(item)

    def _output_item_for_sound_set(self, sound_set: OutputSoundSet) -> SongItem | None:
        output_job_dir = sound_set.job_dir.expanduser().resolve()
        for item in self._song_items_by_id.values():
            if item.output_job_dir is not None:
                if item.output_job_dir.expanduser().resolve() == output_job_dir:
                    return item
        return None

    def _choose_rvc_root(self, *_args) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("Select RVC Root"), self.rvc_root_edit.text())
        if not selected:
            return
        self.rvc_root_edit.setText(selected)
        self._save_rvc_settings_from_controls()
        self._refresh_rvc_choices()

    def _refresh_rvc_choices(self, *_args) -> None:
        self._is_loading_rvc_settings = True
        root = Path(self.rvc_root_edit.text().strip() or str(self.settings.rvc.root))
        self._populate_combo(self.model_combo, list_voice_models(root), self.settings.rvc.voice_model, "Select model")
        self._populate_combo(self.index_combo, list_index_files(root), self.settings.rvc.index_file, "No index")
        self._is_loading_rvc_settings = False
        self._save_rvc_settings_from_controls()

    def _populate_combo(self, combo: QComboBox, values: list[str], current_value: str, placeholder: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr(placeholder), "")
        for value in values:
            combo.addItem(value, value)
        if current_value and current_value not in values:
            combo.addItem(current_value, current_value)
        index = combo.findData(current_value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _save_rvc_settings_from_controls(self, *_args) -> None:
        if self._is_loading_rvc_settings:
            return
        rvc_settings = RvcSettings(
            root=Path(self.rvc_root_edit.text().strip() or str(self.settings.rvc.root)),
            voice_model=_combo_value(self.model_combo),
            index_file=_combo_value(self.index_combo),
            pitch=self.pitch_spin.value(),
            device=self.device_combo.currentText(),
            f0_method="rmvpe",
        )
        self.settings = replace(self.settings, rvc=rvc_settings)
        save_app_settings(self.settings)

    def _start_rvc_conversion(self, *_args) -> None:
        if self.current_output_set is None or self.current_work_item is None:
            self.rvc_action.set_status("No output.")
            return
        if not self.settings.rvc.voice_model:
            self.rvc_action.set_status("Select model.")
            return

        self.rvc_action.set_running(True)
        self.rvc_action.set_progress(8)
        self.rvc_action.set_status("Converting")
        sound_set = self.current_output_set
        scope = WorkTaskScope(self.current_work_item.id)
        settings = self.settings.rvc
        worker = TaskWorker(
            lambda progress: _convert_with_progress(
                sound_set.vocals_path,
                sound_set.job_dir,
                settings,
                progress,
            )
        )
        self._run_worker(
            worker,
            lambda result: self._on_rvc_succeeded(scope, sound_set.job_dir, result),
            lambda error: self._on_rvc_failed(scope, error),
            self.rvc_action,
            task_title="Convert Vocal",
            task_detail=sound_set.label,
            action_scope=lambda: scope.is_current(self.current_work_item),
        )

    def _on_rvc_succeeded(self, scope: WorkTaskScope, job_dir: Path, result: object) -> None:
        output_path = getattr(result, "output_path", None)
        if isinstance(output_path, Path):
            updated = self.library.activate_converted_output(job_dir, output_path)
            if updated is not None:
                self._song_items_by_id[updated.id] = updated
        self._refresh_output_sets_after_task(scope, job_dir)
        if scope.is_current(self.current_work_item):
            self.rvc_action.set_progress(100)
            self.rvc_action.set_status("Done")

    def _on_rvc_failed(self, scope: WorkTaskScope, error: str) -> None:
        if not scope.is_current(self.current_work_item):
            return
        self.rvc_action.set_status("Failed")
        self.rvc_action.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

    def _toggle_global_playback(self, *_args) -> None:
        self.model_workspace_page.stop_preview()
        if self.player.is_playing():
            self._pause_playback()
            return

        if self.current_playback_queue is None:
            self._sync_playback_queue_for_page(self.page_stack.currentIndex(), force=True)
        if self.current_playback_queue is None:
            return

        start_ms = (
            0
            if self._playback_position_ms >= self.current_playback_queue.duration_ms
            else self._playback_position_ms
        )
        self._play_current_queue(start_ms)

    def _dismiss_floating_playback(self) -> None:
        queue = self.current_playback_queue
        self._stop_playback(clear_queue=True)
        if queue is not None:
            self._playback_resume_positions.pop((queue.context, queue.source_id), None)
        self._library_preview_song_id = ""

    def _on_model_preview_started(self) -> None:
        if self.player.is_playing():
            self._pause_playback()

    def _play_current_queue(self, start_ms: int = 0) -> None:
        queue = self.current_playback_queue
        if queue is None:
            return

        try:
            preview_paths = [prepare_preview_audio(path) for path in queue.paths]
            duration_ms = max(self.player.duration_ms(path) for path in preview_paths)
            queue = queue.with_duration(duration_ms)
            start_ms = max(0, min(start_ms, queue.duration_ms))
            if start_ms >= queue.duration_ms:
                start_ms = 0
            self.player.play(preview_paths, start_ms=start_ms, volumes=queue.volumes)
        except Exception as exc:
            self._handle_playback_error(queue, exc)
            return

        self.current_playback_queue = queue
        self._playback_position_ms = start_ms
        if queue.context == "output":
            _set_optional_label(self.output_status_label, "")
        elif queue.context == "library":
            _set_optional_label(self.library_status_label, "")
        self._refresh_playback_ui(is_playing=True)
        self._update_output_playheads(start_ms, queue.duration_ms)
        self.playback_timer.start()

    def _pause_playback(self) -> None:
        self._playback_position_ms = self.player.position_ms()
        self.player.pause()
        self.playback_timer.stop()
        self._refresh_playback_ui(is_playing=False)
        self._update_output_playheads(self._playback_position_ms)

    def _seek_global_playback(self, position_ms: int) -> None:
        queue = self.current_playback_queue
        if queue is None:
            return
        self._playback_position_ms = max(0, min(position_ms, queue.duration_ms))
        was_playing = self.player.is_playing()
        if was_playing and self._playback_position_ms >= queue.duration_ms:
            self.player.pause()
            self.playback_timer.stop()
            was_playing = False
        self._refresh_playback_ui(is_playing=was_playing)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
        if was_playing:
            self._play_current_queue(self._playback_position_ms)

    def _seek_output_playback(self, ratio: float) -> None:
        queue = self._output_playback_queue()
        if queue is None:
            _set_optional_label(self.output_status_label, "No output.")
            return
        position_ms = int(queue.duration_ms * max(0.0, min(1.0, ratio)))
        was_playing = self.player.is_playing()
        if self._current_playback_context() != "output":
            self._set_playback_queue(queue)
            if was_playing:
                self._play_current_queue(position_ms)
                return
        self._seek_global_playback(position_ms)

    def _on_output_playback_settings_changed(self) -> None:
        self._queue_current_studio_session_save()
        self._refresh_output_playback_queue()

    def _on_output_track_source_changed(self) -> None:
        if self.current_output_set is not None:
            path = self.converted_track.current_path()
            song = self.library.activate_converted_output(self.current_output_set.job_dir, path)
            if song is not None:
                self._song_items_by_id[song.id] = song
                if self.current_work_item is not None and self.current_work_item.id == song.id:
                    self._assign_work_item(song, persist=False)
            self.vocal_results_panel.select_converted(path)
        self._refresh_output_playback_queue()

    def _restore_current_studio_session(self) -> None:
        item = self.current_song or self.current_work_item
        if item is None:
            self._apply_studio_session(StudioSession())
            return
        try:
            session = self.library.studio_session(item.id)
        except KeyError:
            session = StudioSession()
        self._apply_studio_session(session)

    def _apply_studio_session(self, session: StudioSession) -> None:
        self._is_loading_studio_session = True
        try:
            self.vocal_track.set_mix_state(
                muted=session.original_vocal.muted,
                volume_percent=session.original_vocal.volume_percent,
            )
            self.instrumental_track.set_mix_state(
                muted=session.instrumental.muted,
                volume_percent=session.instrumental.volume_percent,
            )
            self.converted_track.set_mix_state(
                muted=session.converted_vocal.muted,
                volume_percent=session.converted_vocal.volume_percent,
            )
        finally:
            self._is_loading_studio_session = False

    def _queue_current_studio_session_save(self) -> None:
        if self._is_loading_studio_session or self.current_output_set is None:
            return
        item = self.current_song or self.current_work_item
        if item is None:
            return
        self.studio_session_autosave.queue(item.id, self._studio_session_from_tracks())

    def _studio_session_from_tracks(self) -> StudioSession:
        return StudioSession(
            original_vocal=_studio_track_state(self.vocal_track),
            instrumental=_studio_track_state(self.instrumental_track),
            converted_vocal=_studio_track_state(self.converted_track),
        )

    def _on_studio_session_save_failed(self, error: str) -> None:
        _set_optional_label(self.output_status_label, f"Session failed: {_last_error_line(error)}")

    def _sync_global_playback_state(self) -> None:
        queue = self.current_playback_queue
        if queue is None:
            self._stop_playback(clear_queue=True)
            return
        if not self.player.is_playing():
            self.playback_timer.stop()
            self._playback_position_ms = min(self.player.position_ms(), queue.duration_ms)
            self._refresh_playback_ui(is_playing=False)
            self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
            return

        self._playback_position_ms = self.player.position_ms()
        if self._playback_position_ms >= queue.duration_ms:
            self.player.pause()
            self.playback_timer.stop()
            self._playback_position_ms = queue.duration_ms
            self._refresh_playback_ui(is_playing=False)
            self._update_output_playheads(queue.duration_ms, queue.duration_ms)
            return
        self._refresh_playback_ui(is_playing=True)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)

    def _set_playback_queue(
        self,
        queue: PlaybackQueue | None,
        *,
        position_ms: int = 0,
        auto_play: bool = False,
    ) -> None:
        previous_queue = self.current_playback_queue
        if previous_queue is not None and (
            queue is None
            or previous_queue.context != queue.context
            or previous_queue.source_id != queue.source_id
        ):
            previous_position = (
                self.player.position_ms() if self.player.is_playing() else self._playback_position_ms
            )
            self._playback_resume_positions[(previous_queue.context, previous_queue.source_id)] = max(
                0,
                min(previous_position, previous_queue.duration_ms),
            )
        self.player.stop()
        self.playback_timer.stop()
        self.current_playback_queue = queue
        self._playback_position_ms = 0
        if queue is None:
            self.workspace_dock.clear()
            self.floating_playback_panel.clear()
            self._sync_playback_surfaces()
            self._update_output_playheads(0, 0)
            return

        self._library_preview_song_id = queue.source_id if queue.context == "library" else ""
        if queue.context == "library":
            self.workspace_dock.clear()

        self._playback_position_ms = max(0, min(position_ms, queue.duration_ms))
        self._refresh_playback_ui(is_playing=False)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
        if auto_play:
            self._play_current_queue(self._playback_position_ms)

    def _stop_playback(self, update_player: bool = True, *, clear_queue: bool = False) -> None:
        queue = self.current_playback_queue
        if update_player:
            self.player.stop()
        self.playback_timer.stop()
        self._playback_position_ms = 0
        if clear_queue:
            self.current_playback_queue = None
            self.workspace_dock.clear()
            self.floating_playback_panel.clear()
            if queue is not None and queue.context == "library":
                self._library_preview_song_id = ""
            self._sync_playback_surfaces()
            self._update_output_playheads(0, 0)
            return
        self._refresh_playback_ui(is_playing=False)
        duration = self.current_playback_queue.duration_ms if self.current_playback_queue is not None else 0
        self._update_output_playheads(0, duration)

    def _resume_position(self, queue: PlaybackQueue) -> int:
        return max(
            0,
            min(
                self._playback_resume_positions.get((queue.context, queue.source_id), 0),
                queue.duration_ms,
            ),
        )

    def _refresh_output_playback_queue(self) -> None:
        queue = self._output_playback_queue()
        if queue is None:
            if self._current_playback_context() == "output":
                self._stop_playback(clear_queue=True)
            self._update_output_playheads(0, 0)
            return

        current_queue = self.current_playback_queue
        was_playing = self.player.is_playing() and self._current_playback_context() == "output"
        position_ms = self.player.position_ms() if was_playing else self._playback_position_ms

        if self._current_playback_context() == "output":
            if current_queue is not None and current_queue.source_id != queue.source_id:
                self._playback_resume_positions[(current_queue.context, current_queue.source_id)] = max(
                    0,
                    min(position_ms, current_queue.duration_ms),
                )
                self._set_playback_queue(queue, position_ms=self._resume_position(queue))
                return
            self.current_playback_queue = queue
            self._playback_position_ms = max(0, min(position_ms, queue.duration_ms))
            self._refresh_playback_ui(is_playing=was_playing)
            self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
            if was_playing:
                if queue.has_same_sources(current_queue):
                    try:
                        self.player.set_volumes(queue.volumes)
                    except AudioPlaybackError as exc:
                        _set_optional_label(self.output_status_label, f"Volume failed: {_last_error_line(str(exc))}")
                else:
                    self._play_current_queue(self._playback_position_ms)
            return

        if self.page_stack.currentIndex() in {PAGE_VOCAL, PAGE_STUDIO} and not self.player.is_playing():
            self._set_playback_queue(queue, position_ms=self._resume_position(queue))
            return

        self._update_output_playheads(0, queue.duration_ms)

    def _sync_playback_queue_for_page(self, index: int, *, force: bool = False) -> None:
        if self.current_playback_queue is not None and not force:
            return
        if index == PAGE_LIBRARY and self._library_preview_song_id:
            self._load_library_playback_queue(
                self._song_items_by_id.get(self._library_preview_song_id)
            )
        elif index in {PAGE_VOCAL, PAGE_STUDIO}:
            self._refresh_output_playback_queue()

    def _refresh_playback_ui(self, *, is_playing: bool) -> None:
        queue = self.current_playback_queue
        if queue is None:
            self.workspace_dock.clear()
            self.floating_playback_panel.clear()
            self._sync_playback_surfaces()
            self._sync_video_playback(False)
            return

        self.floating_playback_panel.set_queue(queue.title, queue.duration_ms)
        self.floating_playback_panel.set_position(self._playback_position_ms, queue.duration_ms)
        self.floating_playback_panel.set_playing(is_playing)
        if queue.context == "output":
            self.workspace_dock.set_queue(queue.duration_ms)
            self.workspace_dock.set_position(self._playback_position_ms, queue.duration_ms)
            self.workspace_dock.set_playing(is_playing)
        self._sync_playback_surfaces()
        self._sync_video_playback(is_playing)

    def _current_playback_context(self) -> str:
        return self.current_playback_queue.context if self.current_playback_queue is not None else ""

    def _is_playing_context(self, context: str) -> bool:
        return self.player.is_playing() and self._current_playback_context() == context

    def _handle_playback_error(self, queue: PlaybackQueue, error: Exception) -> None:
        target_label = self.output_status_label if queue.context == "output" else self.library_status_label
        _set_optional_label(target_label, f"Playback failed: {_last_error_line(str(error))}")
        self._stop_playback()

    def _playback_track_paths(self) -> list[tuple[Path, float]]:
        tracks: list[tuple[Path, float]] = []
        for track in self.output_tracks:
            path = track.current_path()
            if path is not None:
                tracks.append((path, 0.0 if track.is_muted() else track.volume()))
        return tracks

    def _loaded_track_paths(self) -> list[Path]:
        return [path for track in self.output_tracks for path in [track.current_path()] if path is not None]

    def _output_playback_queue(self) -> PlaybackQueue | None:
        tracks = self._playback_track_paths()
        duration_ms = self._loaded_output_duration_ms()
        if not tracks or duration_ms <= 0:
            return None
        return PlaybackQueue(
            context="output",
            source_id=str(self.current_output_set.job_dir) if self.current_output_set is not None else "",
            title=self.current_output_set.label if self.current_output_set is not None else "Output Sounds",
            paths=tuple(path for path, _volume in tracks),
            volumes=tuple(volume for _path, volume in tracks),
            duration_ms=duration_ms,
        )

    def _update_output_playheads(self, position_ms: int, duration_ms: int | None = None) -> None:
        queue = self.current_playback_queue if self._current_playback_context() == "output" else None
        duration = duration_ms if duration_ms is not None else (queue.duration_ms if queue is not None else 0)
        position = max(0, min(position_ms, duration)) if duration > 0 else 0
        for track in self.output_tracks:
            track.set_playhead_ratio(position / duration if duration > 0 else 0.0)
        self.vocal_results_panel.set_playhead_ratio(position / duration if duration > 0 else 0.0)

    def _loaded_output_duration_ms(self) -> int:
        return self._duration_ms_for_paths(self._loaded_track_paths())

    def _duration_ms_for_paths(self, paths: list[Path]) -> int:
        durations = []
        for path in paths:
            try:
                durations.append(read_audio_metadata(path).duration_ms)
            except Exception:
                continue
        return max(durations, default=0)

    def _refresh_export_page(self) -> None:
        if not hasattr(self, "export_page"):
            return
        songs = sorted(
            self._song_items_by_id.values(),
            key=lambda item: (item.title.casefold(), item.id),
        )
        selected_id = self._export_song_id if self._export_song_id in self._song_items_by_id else ""
        if not selected_id and self.current_work_item is not None:
            selected_id = self.current_work_item.id
        if not selected_id and songs:
            selected_id = songs[0].id
        self._export_song_id = selected_id
        self.export_page.set_songs(((item.id, item.title) for item in songs), selected_id)
        song = self._song_items_by_id.get(selected_id)
        if song is None:
            self.export_page.set_exports((), (), None)
            self.export_page.set_target_song("", audio_enabled=False, video_enabled=False)
            return
        try:
            audio_exports = self.library.audio_exports(song.id)
            video_exports = self.library.video_exports(song.id)
            export_dir = self.library.audio_export_dir(song.id).parent
            video_source = self.library.video_source(song.id)
        except KeyError:
            audio_exports = ()
            video_exports = ()
            export_dir = None
            video_source = VideoSource()
        capabilities = build_work_song_capabilities(
            song,
            output_available=(
                song.output_job_dir is not None
                and load_output_sound_set(song.output_job_dir, self.settings.output_root) is not None
            ),
        )
        has_local_video = video_source.path is not None and video_source.path.is_file()
        self.export_page.set_exports(audio_exports, video_exports, export_dir)
        self.export_page.set_target_song(
            song.id,
            audio_enabled=capabilities.can_export,
            video_enabled=capabilities.can_export and has_local_video,
        )

    def _on_export_song_changed(self, song_id: str) -> None:
        self._export_song_id = song_id
        self._refresh_export_page()

    def _is_export_song(self, song_id: str) -> bool:
        return bool(song_id) and self._export_song_id == song_id

    def _start_audio_mix_export(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            self.export_page.set_audio_status("Select a song.")
            return

        self.studio_session_autosave.flush()
        self.export_page.set_audio_running(True)
        self.export_page.set_audio_progress(0)
        self.export_page.set_audio_status("Exporting audio mix")
        scope = WorkTaskScope(song_id)
        worker = TaskWorker(
            lambda progress: _run_with_progress(lambda: self.library.export_audio_mix(song_id), progress)
        )
        self._run_worker(
            worker,
            lambda result: self._on_audio_mix_export_succeeded(scope, result),
            lambda error: self._on_audio_mix_export_failed(scope, error),
            self.export_page.audio_action,
            task_title="Export Mix",
            task_detail=song.title,
            action_scope=lambda: self._is_export_song(scope.song_id),
        )

    def _on_audio_mix_export_succeeded(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_export_page()
        if not self._is_export_song(scope.song_id):
            return
        exported = result if isinstance(result, Path) else None
        self.export_page.set_audio_progress(100)
        self.export_page.set_audio_status(
            "Audio mix exported",
            str(exported) if exported is not None else "",
        )

    def _on_audio_mix_export_failed(self, scope: WorkTaskScope, error: str) -> None:
        self._refresh_export_page()
        if not self._is_export_song(scope.song_id):
            return
        self.export_page.set_audio_status(f"Export failed: {_last_error_line(error)}", error)

    def _export_track(self, path: Path) -> None:
        item = self.current_song or self.current_work_item
        if self.current_output_set is None or item is None:
            _set_optional_label(self.output_status_label, "No output.")
            return

        try:
            output_dir = self.library.audio_export_dir(item.id)
        except KeyError:
            _set_optional_label(self.output_status_label, "No output.")
            return
        scope = WorkTaskScope(item.id)
        _set_optional_label(self.output_status_label, "Exporting track")
        worker = TaskWorker(
            lambda progress: _run_with_progress(lambda: export_audio_file(path.stem, path, output_dir), progress)
        )
        self._run_worker(
            worker,
            lambda result: self._on_track_export_succeeded(scope, result),
            lambda error: self._on_track_export_failed(scope, error),
            None,
            task_title="Export Track",
            task_detail=path.name,
        )

    def _on_track_export_succeeded(self, scope: WorkTaskScope, result: object) -> None:
        if not scope.is_current(self.current_work_item):
            return
        exported = result if isinstance(result, Path) else None
        _set_optional_label(self.output_status_label, "Track exported")
        self.output_status_label.setToolTip(str(exported) if exported is not None else "")
        self._refresh_export_page()

    def _on_track_export_failed(self, scope: WorkTaskScope, error: str) -> None:
        if not scope.is_current(self.current_work_item):
            return
        _set_optional_label(self.output_status_label, f"Track failed: {_last_error_line(error)}")

    def _open_track_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            _set_optional_label(self.output_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _open_export_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path if path.exists() else path.parent)
        except Exception as exc:
            self.export_page.set_audio_status(f"Open failed: {_last_error_line(str(exc))}")

    def _use_model_in_convert(self, record: RvcModelRecord) -> None:
        inference_model = record.inference_model
        if inference_model is None or not inference_model.is_file():
            self.model_workspace_page.show_status("This model has no usable inference file.")
            return

        index_file = record.index_file
        rvc_settings = replace(
            self.settings.rvc,
            root=record.runtime_root,
            voice_model=str(inference_model.resolve()),
            index_file=str(index_file.resolve()) if index_file is not None and index_file.is_file() else "",
            pitch=record.default_pitch,
            device=record.default_device,
            f0_method="rmvpe",
        )
        self.settings = replace(self.settings, rvc=rvc_settings)
        save_app_settings(self.settings)
        self._is_loading_rvc_settings = True
        self.rvc_root_edit.setText(str(rvc_settings.root))
        self.pitch_spin.setValue(rvc_settings.pitch)
        self.device_combo.setCurrentText(rvc_settings.device)
        self._is_loading_rvc_settings = False
        self._refresh_rvc_choices()
        self.model_workspace_page.show_status(f"{record.title} is active in Convert.")

    def _open_model_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            self.model_workspace_page.show_status(f"Open failed: {_last_error_line(str(exc))}")

    def _run_worker(
        self,
        worker: TaskWorker,
        on_success: Callable[[object], None],
        on_failed: Callable[[str], None],
        action_widget: TaskProgressTarget | None,
        *,
        task_title: str,
        task_detail: str = "",
        action_scope: Callable[[], bool] | None = None,
    ) -> None:
        task_id = self.processing_queue.start(task_title, task_detail)
        self._workers.append(worker)
        action_key = id(action_widget) if action_widget is not None else None
        if action_key is not None:
            self._action_task_ids[action_key] = task_id

        def owns_action() -> bool:
            return action_key is not None and self._action_task_ids.get(action_key) == task_id

        def action_is_visible() -> bool:
            return owns_action() and (action_scope is None or action_scope())

        def release_action() -> None:
            if not owns_action() or action_widget is None:
                return
            action_widget.set_running(False)
            self._action_task_ids.pop(action_key, None)

        def handle_success(result: object) -> None:
            release_action()
            self.processing_queue.complete(task_id)
            on_success(result)

        def handle_failure(error: str) -> None:
            release_action()
            self.processing_queue.fail(task_id, error)
            on_failed(error)

        def cleanup() -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        if action_widget is not None:
            worker.progress_changed.connect(
                lambda progress: action_widget.set_progress(progress) if action_is_visible() else None
            )
        worker.progress_changed.connect(lambda progress: self.processing_queue.update_progress(task_id, progress))
        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_failure)
        worker.finished.connect(cleanup)
        worker.start()


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedText")
    return label


def _set_optional_label(label: QLabel, text: str) -> None:
    value = text.strip()
    set_translated_text(label, value)
    label.setToolTip("")
    label.setVisible(bool(value))


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    return str(data) if data is not None else combo.currentText().strip()


def _convert_with_progress(input_path: Path, output_dir: Path, settings: RvcSettings, progress) -> object:
    progress(12)
    result = convert_vocal_with_rvc(input_path, output_dir, settings)
    progress(100)
    return result


def _run_with_progress(operation: Callable[[], object], progress: Callable[[int], None]) -> object:
    progress(10)
    result = operation()
    progress(100)
    return result


def _studio_track_state(track: TrackRow) -> StudioTrackState:
    return StudioTrackState(
        muted=track.is_muted(),
        volume_percent=track.volume_percent(),
    )


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"
