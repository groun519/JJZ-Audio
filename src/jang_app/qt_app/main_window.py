from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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

from jang_app.config import APP_ICON_PATH, APP_NAME, LOG_FILE, SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS
from jang_app.pipeline.rvc_convert import convert_vocal_with_rvc, list_index_files, list_voice_models
from jang_app.pipeline.separate import SeparationResult, separate_audio
from jang_app.qt_app.library_row import SongListRow
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.log_drawer import LogDrawer
from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.qt_app.player_bar import GlobalPlayerBar
from jang_app.qt_app.processing_queue_panel import ProcessingQueuePanel
from jang_app.qt_app.segmented_stack import SegmentedStack
from jang_app.qt_app.selected_song_card import SelectedSongCard
from jang_app.qt_app.theme import build_stylesheet, next_theme_mode
from jang_app.qt_app.toast_stack import ToastStack
from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.work_context_bar import WorkContextBar
from jang_app.qt_app.widgets import (
    FeedbackButton,
    FileDropCard,
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
from jang_app.services.audio_export import AudioMixSource, export_audio_file, export_mix
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
from jang_app.services.work_context import build_work_context_display
from jang_app.services.song_library import SongItem, SongLibrary, SongVocalVersion
from jang_app.services.youtube_download import YouTubeDownloadResult, download_youtube_audio


PAGE_LIBRARY = 0
PAGE_VOCAL = 1
PAGE_MODELS = 2
PAGE_STUDIO = 3


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        set_language(settings.language)
        self.library = SongLibrary()
        self.player = AudioPlayer()
        self.processing_queue = ProcessingQueue()
        self._workers: list[TaskWorker] = []
        self._song_items_by_id: dict[str, SongItem] = {}
        self.current_song: SongItem | None = None
        self.current_work_item: SongItem | None = None
        self.current_output_set: OutputSoundSet | None = None
        self.current_playback_queue: PlaybackQueue | None = None
        self._playback_position_ms = 0
        self.selected_video_path: Path | None = None
        self._is_loading_rvc_settings = False

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

    def closeEvent(self, event) -> None:  # noqa: N802
        self.model_workspace_page.stop_preview()
        self.player.stop()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_window_chrome_state()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_processing_queue()

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

    def _build_ui(self) -> None:
        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.page_stack = QStackedWidget()
        root_layout.addWidget(self._build_top_bar(), 0)
        root_layout.addWidget(self._build_navigation_bar(), 0)

        self.page_stack.addWidget(self._build_library_page())
        self.page_stack.addWidget(self._build_vocal_page())
        self.page_stack.addWidget(self._build_models_page())
        self.page_stack.addWidget(self._build_studio_page())

        content_widget = QWidget()
        content_widget.setObjectName("AppContent")
        self._content_widget = content_widget
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 16, 16, 8)
        content_layout.setSpacing(12)
        self.work_context_bar = WorkContextBar()
        content_layout.addWidget(self.work_context_bar, 0)
        content_layout.addWidget(self.page_stack, 1)

        self.player_bar = GlobalPlayerBar()
        self.player_bar.play_toggled.connect(self._toggle_global_playback)
        self.player_bar.seek_requested.connect(self._seek_global_playback)
        content_layout.addWidget(self.player_bar, 0)

        self.processing_queue_panel = ProcessingQueuePanel(self.processing_queue, content_widget)
        self.processing_queue_panel.geometry_changed.connect(self._position_processing_queue)
        self.processing_queue_panel.log_requested.connect(self._open_log_drawer)

        self.toast_stack = ToastStack(self.processing_queue, content_widget)
        self.toast_stack.geometry_changed.connect(self._position_processing_queue)
        self.toast_stack.details_requested.connect(self._open_log_drawer)

        self.log_drawer = LogDrawer(self.processing_queue, content_widget)
        self.log_drawer.close_requested.connect(self._close_log_drawer)
        self.log_drawer.open_location_requested.connect(self._open_log_location)
        QTimer.singleShot(0, self._position_processing_queue)

        self.size_grip = QSizeGrip(content_widget)
        grip_layout = QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 0, 0)
        grip_layout.addStretch(1)
        grip_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        content_layout.addLayout(grip_layout, 0)
        root_layout.addWidget(content_widget, 1)

        self.setCentralWidget(root_widget)

    def _build_top_bar(self) -> QWidget:
        self.title_bar = WindowTitleBar(APP_NAME, APP_ICON_PATH)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_window_maximized)
        self.title_bar.close_requested.connect(self.close)
        return self.title_bar

    def _build_navigation_bar(self) -> QWidget:
        nav_bar = QFrame()
        nav_bar.setObjectName("NavigationBar")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(16, 8, 16, 8)
        nav_layout.setSpacing(8)

        self.library_nav_button = FeedbackButton("Library")
        self.library_nav_button.setObjectName("NavButton")
        self.library_nav_button.setCheckable(True)
        self.library_nav_button.setChecked(True)
        self.vocal_nav_button = FeedbackButton("Vocal")
        self.vocal_nav_button.setObjectName("NavButton")
        self.vocal_nav_button.setCheckable(True)
        self.models_nav_button = FeedbackButton("Models")
        self.models_nav_button.setObjectName("NavButton")
        self.models_nav_button.setCheckable(True)
        self.studio_nav_button = FeedbackButton("Studio")
        self.studio_nav_button.setObjectName("NavButton")
        self.studio_nav_button.setCheckable(True)

        self.page_nav_group = QButtonGroup(self)
        self.page_nav_group.setExclusive(True)
        self.page_nav_group.addButton(self.library_nav_button, PAGE_LIBRARY)
        self.page_nav_group.addButton(self.vocal_nav_button, PAGE_VOCAL)
        self.page_nav_group.addButton(self.models_nav_button, PAGE_MODELS)
        self.page_nav_group.addButton(self.studio_nav_button, PAGE_STUDIO)
        self.page_nav_group.idClicked.connect(self._navigate_to_page)

        self.theme_button = ThemeToggleButton()
        self.theme_button.clicked.connect(self._toggle_theme)
        self.language_button = SvgIconButton("globe", size=30)
        self.language_button.setObjectName("TitleBarLanguageButton")
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
        self.title_bar.add_action_widget(self.language_button)
        self.title_bar.add_action_widget(self.theme_button)

        nav_layout.addStretch(1)
        for button in (
            self.library_nav_button,
            self.vocal_nav_button,
            self.models_nav_button,
            self.studio_nav_button,
        ):
            nav_layout.addWidget(button, 0)
        nav_layout.addStretch(1)
        return nav_bar

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
        add_button = FeedbackButton("Add")
        add_button.clicked.connect(self._choose_audio_files)
        list_header.addWidget(list_title, 1)
        list_header.addWidget(add_button, 0)

        self.song_list = QListWidget()
        self.song_list.currentItemChanged.connect(self._on_song_selection_changed)

        list_layout.addLayout(list_header)
        list_layout.addWidget(self.song_list, 1)

        layout.addWidget(import_panel, 1)
        layout.addWidget(list_panel, 3)
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

        self.vocal_song_card = SelectedSongCard()
        self.vocal_song_combo = self.vocal_song_card.combo
        self.vocal_song_card.song_changed.connect(self._on_workspace_song_changed)
        self.vocal_steps = SegmentedStack(
            (
                ("Separate", self._build_separate_step_page()),
                ("Convert", self._build_convert_step_page()),
            )
        )

        left_layout.addWidget(self.vocal_song_card, 0)
        left_layout.addWidget(self.vocal_steps, 1)

        self.vocal_results_panel = VocalResultsPanel()
        self.vocal_results_panel.output_selected.connect(self._activate_vocal_output_version)
        self.vocal_results_panel.converted_selected.connect(self._activate_vocal_converted_version)
        self.vocal_results_panel.open_location_requested.connect(self._open_vocal_output_location)
        self.vocal_results_panel.remove_output_requested.connect(self._remove_vocal_output_version)
        self.vocal_results_panel.open_studio_requested.connect(self._open_current_song_in_studio)
        self.vocal_results_panel.seek_requested.connect(self._seek_output_playback)

        layout.addWidget(left_panel, 0)
        layout.addWidget(self.vocal_results_panel, 1)
        return page

    def _build_studio_page(self) -> QWidget:
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

        self.studio_song_card = SelectedSongCard()
        self.studio_song_combo = self.studio_song_card.combo
        self.studio_song_card.song_changed.connect(self._on_workspace_song_changed)
        self.song_selector_cards = (self.vocal_song_card, self.studio_song_card)
        self.studio_steps = SegmentedStack(
            (
                ("Mix", self._build_mix_export_panel()),
                ("Video", self._build_video_step_page()),
            )
        )

        left_layout.addWidget(self.studio_song_card, 0)
        left_layout.addWidget(self.studio_steps, 1)

        layout.addWidget(left_panel, 0)
        layout.addWidget(self._build_output_panel(), 1)
        return page

    def _build_video_step_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("Card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel("Video")
        title.setObjectName("SectionTitle")
        select_button = FeedbackButton("Select Video")
        select_button.setObjectName("PrimaryButton")
        select_button.clicked.connect(self._choose_video_file)
        self.selected_video_label = QLabel("")
        self.selected_video_label.setObjectName("MutedText")
        self.selected_video_label.setWordWrap(True)
        self.selected_video_label.hide()

        preview_surface = QFrame()
        preview_surface.setObjectName("VideoPreviewSurface")
        preview_surface.setMinimumHeight(240)

        layout.addWidget(title)
        layout.addWidget(select_button)
        layout.addWidget(self.selected_video_label)
        layout.addWidget(preview_surface, 1)
        return page

    def _build_models_page(self) -> QWidget:
        self.model_workspace_page = ModelWorkspacePage(self.settings.rvc.root)
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

    def _build_mix_export_panel(self) -> QWidget:
        mix_panel = QFrame()
        mix_panel.setObjectName("Card")
        mix_layout = QVBoxLayout(mix_panel)
        mix_layout.setContentsMargins(22, 22, 22, 22)
        mix_layout.setSpacing(14)
        mix_title = QLabel("Mix Export")
        mix_title.setObjectName("SectionTitle")
        self.export_mix_button = FeedbackButton("Export Mix")
        self.export_mix_button.setObjectName("PrimaryButton")
        self.export_mix_button.clicked.connect(self._export_mix)
        self.mix_status_label = QLabel("")
        self.mix_status_label.setObjectName("MutedText")
        self.mix_status_label.setWordWrap(True)
        self.mix_status_label.hide()
        mix_layout.addWidget(mix_title)
        mix_layout.addWidget(self.export_mix_button)
        mix_layout.addWidget(self.mix_status_label)
        mix_layout.addStretch(1)
        return mix_panel

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
        self.theme_button.set_theme_mode(self.settings.theme_mode)
        self.language_button.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "player_bar"):
            self.player_bar.set_theme_mode(self.settings.theme_mode)
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
        set_translated_tooltip(self.language_button, "Language")
        for language, action in self.language_actions.items():
            action.setChecked(language == self.settings.language)
        for card in getattr(self, "song_selector_cards", ()):
            card.apply_language()
        self.player_bar.apply_language()
        self.processing_queue_panel.apply_language()
        self.toast_stack.apply_language()
        self.work_context_bar.apply_language()
        self.log_drawer.apply_language()
        self.model_workspace_page.apply_language()
        self.vocal_results_panel.apply_language()

    def _position_processing_queue(self) -> None:
        if not hasattr(self, "processing_queue_panel") or not hasattr(self, "player_bar"):
            return
        panel = self.processing_queue_panel
        parent = self._content_widget
        player_top = self.player_bar.geometry().top()
        drawer_open = hasattr(self, "log_drawer") and self.log_drawer.isVisible()

        if drawer_open:
            drawer = self.log_drawer
            top_position = self.work_context_bar.geometry().bottom() + 12 if self.work_context_bar.isVisible() else 16
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

    def _change_language(self, language: str) -> None:
        if language == self.settings.language:
            return
        self.settings = replace(self.settings, language=language)
        save_app_settings(self.settings)
        self._apply_language()

    def _navigate_to_page(self, index: int) -> None:
        if index != PAGE_MODELS:
            self.model_workspace_page.stop_preview()
        self.page_stack.setCurrentIndex(index)
        self.library_nav_button.setChecked(index == PAGE_LIBRARY)
        self.vocal_nav_button.setChecked(index == PAGE_VOCAL)
        self.models_nav_button.setChecked(index == PAGE_MODELS)
        self.studio_nav_button.setChecked(index == PAGE_STUDIO)
        self._sync_playback_queue_for_page(index)

    def _navigate_to_vocal_step(self, index: int) -> None:
        self.vocal_steps.set_current_index(index)

    def _navigate_to_studio_step(self, index: int) -> None:
        self.studio_steps.set_current_index(index)

    def _open_current_song_in_studio(self, *_args) -> None:
        if self.current_output_set is None:
            return
        self._navigate_to_page(PAGE_STUDIO)
        self._navigate_to_studio_step(0)

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
        self.selected_video_path = Path(filename).expanduser().resolve()
        _set_optional_label(self.selected_video_label, self.selected_video_path.name)

    def _add_songs(self, paths: list[Path]) -> None:
        added = self.library.add_paths(paths)
        self._refresh_song_list()
        if not added:
            _set_optional_label(self.library_status_label, "Unsupported file.")
            return

        _set_optional_label(self.library_status_label, f"Added {len(added)}")
        self._select_song(added[0].id)

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
            self._select_song(song.id)
        self.youtube_card.url_edit.clear()
        self.youtube_card.set_progress(100)
        self.youtube_card.set_status("Done")
        _set_optional_label(self.library_status_label, f"Downloaded: {download_result.title}")

    def _on_youtube_download_failed(self, error: str) -> None:
        self.youtube_card.set_status("Failed")
        self.youtube_card.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

    def _refresh_song_list(self) -> None:
        selected_id = self._current_song_id()
        studio_song_id = self.current_song.id if self.current_song is not None else ""
        work_item_id = self.current_work_item.id if self.current_work_item is not None else ""
        self.song_list.blockSignals(True)
        self.song_list.clear()
        self._song_items_by_id = {item.id: item for item in self.library.items()}
        self.current_song = self._song_items_by_id.get(studio_song_id)
        self.current_work_item = self._song_items_by_id.get(work_item_id)
        for item in self._song_items_by_id.values():
            metadata = build_song_display_metadata(item, self.settings.output_root)
            row = SongListRow(item.id, item.title, metadata)
            row.set_theme_mode(self.settings.theme_mode)
            apply_widget_language(row)
            row.use_requested.connect(self._use_library_item)
            row.rename_requested.connect(self._rename_library_item)
            row.remove_requested.connect(self._remove_library_item)
            list_item = make_list_item(row)
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self.song_list.addItem(list_item)
            self.song_list.setItemWidget(list_item, row)
        self.song_list.blockSignals(False)
        if selected_id and self._select_song(selected_id):
            pass
        elif self.song_list.count() > 0:
            self.song_list.setCurrentRow(0)
        else:
            self._on_song_selection_changed()
        self._sync_song_row_selection()
        self._refresh_song_selectors()

    def _select_song(self, song_id: str) -> bool:
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == song_id:
                self.song_list.setCurrentItem(item)
                return True
        return False

    def _on_song_selection_changed(self, *_args) -> None:
        song = self._selected_song()
        self._sync_song_row_selection()
        if self.player.is_playing() and self._current_playback_context() != "library":
            return
        if self.page_stack.currentIndex() == PAGE_LIBRARY or self._current_playback_context() == "library":
            self._load_library_playback_queue(song, auto_play=self._is_playing_context("library"))

    def _sync_song_row_selection(self) -> None:
        selected_id = self._current_song_id()
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            row = self.song_list.itemWidget(item)
            if hasattr(row, "set_selected"):
                row.set_selected(item.data(Qt.ItemDataRole.UserRole) == selected_id)

    def _selected_song(self) -> SongItem | None:
        current_item = self.song_list.currentItem()
        if current_item is None:
            return None
        return self._song_items_by_id.get(current_item.data(Qt.ItemDataRole.UserRole))

    def _current_song_id(self) -> str:
        current_item = self.song_list.currentItem()
        return current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else ""

    def _rename_library_item(self, song_id: str, new_title: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            return

        if not self.library.rename_item(song_id, new_title):
            _set_optional_label(self.library_status_label, "Name required.")
            return

        _set_optional_label(self.library_status_label, "Renamed")
        self._refresh_song_list()
        self._select_song(song_id)
        if self.current_song is not None and self.current_song.id == song_id:
            self.current_song = self._song_items_by_id.get(song_id)
            self._refresh_song_selectors(preferred_song_id=song_id)
        if self.current_work_item is not None and self.current_work_item.id == song_id:
            self.current_work_item = self._song_items_by_id.get(song_id)
        self._sync_work_context_bar()

    def _remove_library_item(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            return

        was_current_song = self.current_song is not None and self.current_song.id == song_id
        was_work_item = self.current_work_item is not None and self.current_work_item.id == song_id
        was_selected_song = self._current_song_id() == song_id
        if was_selected_song and self._current_playback_context() == "library":
            self._stop_playback(clear_queue=True)
        if not self.library.remove_item(song_id):
            return

        if was_current_song:
            self._set_current_song(None)
        elif was_work_item:
            self.current_work_item = None
            self._sync_work_context_bar()
        _set_optional_label(self.library_status_label, "Removed")
        self._refresh_song_list()

    def _refresh_song_selectors(self, preferred_song_id: str | None = None) -> None:
        if not hasattr(self, "vocal_song_card") or not hasattr(self, "studio_song_card"):
            return

        selected_id = preferred_song_id or (self.current_song.id if self.current_song is not None else "")
        source_songs = self._source_song_items()
        song_options = tuple((song.id, song.title) for song in source_songs)
        self.song_selector_cards = (self.vocal_song_card, self.studio_song_card)
        for card in self.song_selector_cards:
            card.set_songs(song_options, selected_id)
        if selected_id and selected_id not in self._song_items_by_id:
            self.current_song = None
            if self.current_work_item is not None and self.current_work_item.kind == "source":
                self.current_work_item = None
        self._sync_work_context_bar()

    def _source_song_items(self) -> list[SongItem]:
        return sorted(
            [item for item in self._song_items_by_id.values() if item.kind == "source"],
            key=lambda item: item.title.casefold(),
        )

    def _on_workspace_song_changed(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id) if song_id else None
        self._set_current_song(song)
        for card in self.song_selector_cards:
            card.select_song(song_id)

    def _set_current_song(self, song: SongItem | None) -> None:
        self.current_song = song
        self.current_work_item = song
        self.separation_action.set_action_enabled(song is not None)
        self.separation_action.set_progress(0)
        self.separation_action.set_status("")
        if song is None or song.output_job_dir is None:
            self._apply_output_set(None)
            return
        sound_set = load_output_sound_set(song.output_job_dir, self.settings.output_root)
        self._select_output_set(song.output_job_dir)
        self._apply_output_set(sound_set)

    def _sync_work_context_bar(self) -> None:
        self.work_context_bar.set_display(
            build_work_context_display(self.current_work_item, self.current_output_set, self.settings.output_root)
        )

    def _select_work_song(self, song: SongItem) -> None:
        self._refresh_song_selectors(preferred_song_id=song.id)
        self._set_current_song(song)

    def _use_selected_song(self, *_args) -> None:
        self._use_library_item(self._current_song_id())

    def _use_library_item(self, song_id: str) -> None:
        if song_id:
            self._select_song(song_id)
        song = self._selected_song()
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
        self._set_playback_queue(queue, auto_play=auto_play)

    def _start_separation(self, *_args) -> None:
        if self.current_song is None:
            self.separation_action.set_status("Select song.")
            return

        self._stop_playback()
        self.separation_action.set_running(True)
        self.separation_action.set_progress(3)
        self.separation_action.set_status("Separating")
        song = self.current_song
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
            lambda result: self._on_separation_succeeded(song.id, result),
            self._on_separation_failed,
            self.separation_action,
            task_title="Separate Audio",
            task_detail=song.title,
        )

    def _on_separation_succeeded(self, song_id: str, result: object) -> None:
        separation_result = result if isinstance(result, SeparationResult) else None
        if separation_result is None:
            self.separation_action.set_status("Failed")
            return

        self.separation_action.set_progress(100)
        self.separation_action.set_status("Done")
        self.library.register_output(
            song_id,
            separation_result.job_dir,
            separation_result.job_dir.parent.name,
        )
        self._refresh_output_sets(preferred_job_dir=separation_result.job_dir)

    def _on_separation_failed(self, error: str) -> None:
        self.separation_action.set_status("Failed")
        self.separation_action.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

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

        sound_set = load_output_sound_set(song.output_job_dir, self.settings.output_root)
        if sound_set is None:
            _set_optional_label(self.library_status_label, "Load failed.")
            return

        self.current_song = None
        self.current_work_item = song
        for card in self.song_selector_cards:
            card.select_song("")
        self.separation_action.set_action_enabled(False)
        self.separation_action.set_progress(0)
        self.separation_action.set_status("")
        self._select_output_set(sound_set.job_dir)
        self._apply_output_set(sound_set)
        _set_optional_label(self.library_status_label, "Loaded")
        self._navigate_to_page(PAGE_STUDIO)
        self._navigate_to_studio_step(0)

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

    def _activate_vocal_output_version(self, job_dir: Path) -> None:
        self._select_output_set(job_dir)
        self._activate_output_job(job_dir)

    def _activate_output_job(self, job_dir: Path) -> None:
        song = self.library.activate_output(job_dir)
        if song is not None:
            self._song_items_by_id[song.id] = song
            self.current_song = song if song.kind == "source" else None
            self.current_work_item = song
            for card in self.song_selector_cards:
                card.select_song(song.id if song.kind == "source" else "")
        self._apply_output_set(load_output_sound_set(job_dir, self.settings.output_root))

    def _activate_vocal_converted_version(self, path: Path | None) -> None:
        if self.current_output_set is None:
            return
        song = self.library.activate_converted_output(self.current_output_set.job_dir, path)
        if song is not None:
            self._song_items_by_id[song.id] = song
            if self.current_song is not None and self.current_song.id == song.id:
                self.current_song = song
            if self.current_work_item is not None and self.current_work_item.id == song.id:
                self.current_work_item = song
        self.converted_track.select_path(path)
        self._refresh_output_playback_queue()
        self._sync_work_context_bar()

    def _open_vocal_output_location(self, job_dir: Path) -> None:
        try:
            open_in_file_browser(job_dir)
        except Exception as exc:
            _set_optional_label(self.output_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _remove_vocal_output_version(self, job_dir: Path) -> None:
        updated = self.library.detach_output(job_dir)
        if updated is None:
            return
        self._song_items_by_id[updated.id] = updated
        self.current_song = updated if updated.kind == "source" else None
        self.current_work_item = updated
        preferred = updated.output_job_dir
        self._refresh_output_sets(preferred_job_dir=preferred, select_fallback=preferred is not None)
        if preferred is None:
            self._apply_output_set(None)
        for card in self.song_selector_cards:
            card.select_song(updated.id if updated.kind == "source" else "")
        self._sync_work_context_bar()

    def _apply_output_set(self, sound_set: OutputSoundSet | None) -> None:
        self.current_output_set = sound_set
        self._sync_current_work_output_item(sound_set)
        if sound_set is None:
            self.vocal_track.set_single_path(None)
            self.instrumental_track.set_single_path(None)
            self.converted_track.set_options([])
            self.vocal_results_panel.set_versions((), None)
            self.rvc_action.set_action_enabled(False)
            self.rvc_action.set_status("")
            _set_optional_label(self.mix_status_label, "")
            _set_optional_label(self.output_status_label, "")
            self._refresh_output_playback_queue()
            self._sync_work_context_bar()
            return

        self.vocal_track.set_single_path(sound_set.vocals_path)
        self.instrumental_track.set_single_path(sound_set.instrumental_path)
        versions = self._current_vocal_versions()
        selected_version = next(
            (version for version in versions if version.job_dir == sound_set.job_dir),
            None,
        )
        selected_converted = selected_version.active_converted_path if selected_version is not None else None
        self.converted_track.set_options(list(sound_set.converted_vocal_paths), selected_converted)
        self.vocal_results_panel.set_versions(versions, sound_set.job_dir)
        self.rvc_action.set_action_enabled(True)
        self.rvc_action.set_progress(0)
        self.rvc_action.set_status("")
        _set_optional_label(self.mix_status_label, "")
        _set_optional_label(self.output_status_label, "")
        self._refresh_output_playback_queue()
        self._sync_work_context_bar()

    def _current_vocal_versions(self) -> tuple[SongVocalVersion, ...]:
        item = self.current_song or self.current_work_item
        if item is None:
            return ()
        try:
            return self.library.vocal_versions(item.id)
        except KeyError:
            return ()

    def _sync_current_work_output_item(self, sound_set: OutputSoundSet | None) -> None:
        if self.current_song is not None:
            return
        if sound_set is None:
            if self.current_work_item is not None and self.current_work_item.kind == "output":
                self.current_work_item = None
            return
        self.current_work_item = self._output_item_for_sound_set(sound_set)

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
        if self.current_output_set is None:
            self.rvc_action.set_status("No output.")
            return
        if not self.settings.rvc.voice_model:
            self.rvc_action.set_status("Select model.")
            return

        self.rvc_action.set_running(True)
        self.rvc_action.set_progress(8)
        self.rvc_action.set_status("Converting")
        sound_set = self.current_output_set
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
            lambda result: self._on_rvc_succeeded(sound_set.job_dir, result),
            self._on_rvc_failed,
            self.rvc_action,
            task_title="Convert Vocal",
            task_detail=sound_set.label,
        )

    def _on_rvc_succeeded(self, job_dir: Path, result: object) -> None:
        self.rvc_action.set_progress(100)
        self.rvc_action.set_status("Done")
        output_path = getattr(result, "output_path", None)
        if isinstance(output_path, Path):
            updated = self.library.activate_converted_output(job_dir, output_path)
            if updated is not None:
                self._song_items_by_id[updated.id] = updated
        preferred = self.current_output_set.job_dir if self.current_output_set is not None else job_dir
        self._refresh_output_sets(preferred_job_dir=preferred)

    def _on_rvc_failed(self, error: str) -> None:
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
            start_ms = max(0, min(start_ms, duration_ms))
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
        self._refresh_player_bar(is_playing=True)
        self._update_output_playheads(start_ms, queue.duration_ms)
        self.playback_timer.start()

    def _pause_playback(self) -> None:
        self._playback_position_ms = self.player.position_ms()
        self.player.pause()
        self.playback_timer.stop()
        self._refresh_player_bar(is_playing=False)
        self._update_output_playheads(self._playback_position_ms)

    def _seek_global_playback(self, position_ms: int) -> None:
        queue = self.current_playback_queue
        if queue is None:
            return
        duration = queue.duration_ms
        self._playback_position_ms = max(0, min(position_ms, duration)) if duration > 0 else 0
        self._refresh_player_bar(is_playing=self.player.is_playing())
        self._update_output_playheads(self._playback_position_ms, duration)
        if self.player.is_playing():
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
        self._refresh_output_playback_queue()

    def _on_output_track_source_changed(self) -> None:
        if self.current_output_set is not None:
            path = self.converted_track.current_path()
            song = self.library.activate_converted_output(self.current_output_set.job_dir, path)
            if song is not None:
                self._song_items_by_id[song.id] = song
                if self.current_song is not None and self.current_song.id == song.id:
                    self.current_song = song
                if self.current_work_item is not None and self.current_work_item.id == song.id:
                    self.current_work_item = song
            self.vocal_results_panel.select_converted(path)
        self._refresh_output_playback_queue()

    def _sync_global_playback_state(self) -> None:
        queue = self.current_playback_queue
        if queue is None:
            self._stop_playback(clear_queue=True)
            return
        if not self.player.is_playing():
            self.playback_timer.stop()
            self._playback_position_ms = min(self.player.position_ms(), queue.duration_ms)
            self._refresh_player_bar(is_playing=False)
            self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
            return

        self._playback_position_ms = self.player.position_ms()
        self._refresh_player_bar(is_playing=True)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)

    def _set_playback_queue(
        self,
        queue: PlaybackQueue | None,
        *,
        position_ms: int = 0,
        auto_play: bool = False,
    ) -> None:
        self.player.stop()
        self.playback_timer.stop()
        self.current_playback_queue = queue
        self._playback_position_ms = 0
        if queue is None:
            self.player_bar.clear()
            self._update_output_playheads(0, 0)
            return

        self._playback_position_ms = max(0, min(position_ms, queue.duration_ms)) if queue.duration_ms > 0 else 0
        self._refresh_player_bar(is_playing=False)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
        if auto_play:
            self._play_current_queue(self._playback_position_ms)

    def _stop_playback(self, update_player: bool = True, *, clear_queue: bool = False) -> None:
        if update_player:
            self.player.stop()
        self.playback_timer.stop()
        self._playback_position_ms = 0
        if clear_queue:
            self.current_playback_queue = None
            self.player_bar.clear()
            self._update_output_playheads(0, 0)
            return
        self._refresh_player_bar(is_playing=False)
        duration = self.current_playback_queue.duration_ms if self.current_playback_queue is not None else 0
        self._update_output_playheads(0, duration)

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
            self.current_playback_queue = queue
            self._playback_position_ms = max(0, min(position_ms, queue.duration_ms))
            self._refresh_player_bar(is_playing=was_playing)
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
            self._set_playback_queue(queue)
            return

        self._update_output_playheads(0, queue.duration_ms)

    def _sync_playback_queue_for_page(self, index: int, *, force: bool = False) -> None:
        if self.player.is_playing() and not force:
            return
        if index == PAGE_LIBRARY:
            self._load_library_playback_queue(self._selected_song())
        elif index in {PAGE_VOCAL, PAGE_STUDIO}:
            self._refresh_output_playback_queue()

    def _refresh_player_bar(self, *, is_playing: bool) -> None:
        queue = self.current_playback_queue
        if queue is None:
            self.player_bar.clear()
            return
        self.player_bar.set_queue(_playback_context_label(queue.context), queue.title, queue.duration_ms)
        self.player_bar.set_position(self._playback_position_ms, queue.duration_ms)
        self.player_bar.set_playing(is_playing)

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

    def _export_mix(self, *_args) -> None:
        if self.current_output_set is None:
            _set_optional_label(self.mix_status_label, "No output.")
            return

        sources = [
            AudioMixSource(_track_export_label(track), path, volume)
            for track in self.output_tracks
            for path, volume in [(track.current_path(), track.volume())]
            if path is not None and not track.is_muted()
        ]
        if not sources:
            _set_optional_label(self.mix_status_label, "No active tracks.")
            return

        output_path = self.current_output_set.job_dir / "exports" / "mix.wav"
        self.export_mix_button.setDisabled(True)
        _set_optional_label(self.mix_status_label, "Exporting mix")
        worker = TaskWorker(lambda progress: _run_with_progress(lambda: export_mix(sources, output_path), progress))
        self._run_worker(
            worker,
            self._on_mix_export_succeeded,
            self._on_mix_export_failed,
            None,
            task_title="Export Mix",
            task_detail=self.current_output_set.label,
        )

    def _on_mix_export_succeeded(self, result: object) -> None:
        self.export_mix_button.setEnabled(True)
        exported = result if isinstance(result, Path) else None
        _set_optional_label(self.mix_status_label, "Mix exported")
        self.mix_status_label.setToolTip(str(exported) if exported is not None else "")

    def _on_mix_export_failed(self, error: str) -> None:
        self.export_mix_button.setEnabled(True)
        _set_optional_label(self.mix_status_label, f"Export failed: {_last_error_line(error)}")

    def _export_track(self, path: Path) -> None:
        if self.current_output_set is None:
            _set_optional_label(self.mix_status_label, "No output.")
            return

        output_dir = self.current_output_set.job_dir / "exports"
        _set_optional_label(self.mix_status_label, "Exporting track")
        worker = TaskWorker(
            lambda progress: _run_with_progress(lambda: export_audio_file(path.stem, path, output_dir), progress)
        )
        self._run_worker(
            worker,
            self._on_track_export_succeeded,
            self._on_track_export_failed,
            None,
            task_title="Export Track",
            task_detail=path.name,
        )

    def _on_track_export_succeeded(self, result: object) -> None:
        exported = result if isinstance(result, Path) else None
        _set_optional_label(self.mix_status_label, "Track exported")
        self.mix_status_label.setToolTip(str(exported) if exported is not None else "")

    def _on_track_export_failed(self, error: str) -> None:
        _set_optional_label(self.mix_status_label, f"Track failed: {_last_error_line(error)}")

    def _open_track_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            _set_optional_label(self.mix_status_label, f"Open failed: {_last_error_line(str(exc))}")

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
    ) -> None:
        task_id = self.processing_queue.start(task_title, task_detail)
        self._workers.append(worker)

        def handle_success(result: object) -> None:
            if action_widget is not None:
                action_widget.set_running(False)
            self.processing_queue.complete(task_id)
            on_success(result)

        def handle_failure(error: str) -> None:
            if action_widget is not None:
                action_widget.set_running(False)
            self.processing_queue.fail(task_id, error)
            on_failed(error)

        def cleanup() -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        if action_widget is not None:
            worker.progress_changed.connect(action_widget.set_progress)
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


def _track_export_label(track: TrackRow) -> str:
    return track.title_label.text().replace(" ", "_").lower()


def _playback_context_label(context: str) -> str:
    if context == "output":
        return "Output"
    if context == "library":
        return "Library"
    return ""


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"
