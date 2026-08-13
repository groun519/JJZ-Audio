from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import (
    APP_ICON_PATH,
    APP_NAME,
    APP_PATHS,
    GOOGLE_ICON_PATH,
    GOOGLE_OAUTH_CLIENT_PATH,
    LOG_FILE,
    RVC_RUNTIME_DIR,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
)
from jang_app.pipeline.rvc_convert import (
    RvcConversionResult,
    convert_vocal_with_rvc,
    list_index_files,
)
from jang_app.pipeline.separate import SeparationResult, separate_audio
from jang_app.qt_app.confirmation_dialog import ConfirmationDialog
from jang_app.qt_app.collapsible_card_header import CollapsibleCardHeader
from jang_app.qt_app.conversion_result_browser import ConversionResultBrowser
from jang_app.qt_app.export_page import ExportPage
from jang_app.qt_app.google_account_button import GoogleAccountButton
from jang_app.qt_app.google_drive_controller import GoogleDriveController
from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog
from jang_app.qt_app.library_details_panel import LibraryDetailsPanel
from jang_app.qt_app.library_row import SongListRow
from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_placeholder,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.log_drawer import LogDrawer
from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.qt_app.processing_queue_panel import ProcessingQueueButton, ProcessingQueuePanel
from jang_app.qt_app.primary_navigation import PrimaryNavigationBar
from jang_app.qt_app.result_transport_bar import ResultTransportBar
from jang_app.qt_app.rvc_inference_controls import RvcInferenceControls
from jang_app.qt_app.separation_recipe_selector import SeparationRecipeSelector
from jang_app.qt_app.separation_stem_pool import SeparationStemPoolPanel
from jang_app.qt_app.studio_session_autosave import StudioSessionAutosave
from jang_app.qt_app.studio_editor import StudioEditor
from jang_app.qt_app.studio_transport_bar import StudioTransportBar
from jang_app.qt_app.task_attention import TaskAttentionController
from jang_app.qt_app.theme import build_stylesheet, next_theme_mode
from jang_app.qt_app.text_input_dialog import TextInputDialog
from jang_app.qt_app.toast_stack import ToastStack
from jang_app.qt_app.update_dialog import UpdateDialog
from jang_app.qt_app.update_status_button import (
    STATE_FAILED,
    STATE_READY,
    UpdateStatusButton,
    update_button_position,
)
from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.qt_app.video_preview_panel import VideoPreviewPanel
from jang_app.qt_app.window_chrome import apply_window_corner_style
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.qt_app.widgets import (
    FileDropCard,
    FeedbackButton,
    ScrollSafeComboBox,
    ScrollSafeSpinBox,
    SvgIconButton,
    TaskActionWidget,
    ThemeToggleButton,
    TrackRow,
    TransparentContainer,
    UrlDownloadCard,
    WindowTitleBar,
    attach_transparent_scroll_widget,
    attach_list_item_widget,
)
from jang_app.qt_app.workers import TaskProgressTarget, TaskWorker
from jang_app.services.app_logging import get_logger
from jang_app.services.app_update import (
    DEFAULT_MANIFEST_URL,
    ReleaseManifest,
    UpdatePlan,
    create_update_plan,
    discard_cached_artifacts,
    download_artifact,
    fetch_release_manifest_if_changed,
)
from jang_app.services.audio_export import AudioExportError, AudioMixSource, export_audio_file
from jang_app.services.audio_export_settings import AudioExportSettings
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.audio_player import (
    AudioPlaybackError,
    AudioPlayer,
    PreparedPlaybackAudio,
)
from jang_app.services.video_export_settings import VideoExportSettings
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.command import start_detached_command
from jang_app.services.distribution_channel import application_updates_enabled
from jang_app.services.file_browser import open_in_file_browser
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language, tr
from jang_app.services.job_diagnostics import get_job_diagnostics
from jang_app.services.hardware_diagnostics_state import (
    recorded_hardware_selection,
)
from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set, scan_output_sound_sets
from jang_app.services.playback_queue import PlaybackQueue
from jang_app.services.playback_session import PlaybackSession
from jang_app.services.processing_queue import ProcessingQueue
from jang_app.services.rvc_execution_runtime import settings_for_managed_rvc_runtime
from jang_app.services.rvc_inference_settings import RvcInferenceSettings
from jang_app.services.rvc_model_choices import (
    RvcModelChoice,
    collect_rvc_model_choices,
    resolve_optional_rvc_setting_path,
    rvc_model_choice_from_record,
)
from jang_app.services.rvc_model_workspace import (
    RvcModelRecord,
    RvcModelWorkspace,
)
from jang_app.services.runtime_installation import (
    installed_rvc_runtime_profile,
    installed_runtime_version,
)
from jang_app.services.studio_realtime_audio import (
    prepare_studio_playback_audio,
    studio_effect_chains,
    studio_playback_duration_ms,
    studio_source_layout_signature,
)
from jang_app.services.runtime_bootstrap import install_update_runtime_components
from jang_app.services.rvc_runtime_profile import detect_rvc_runtime_profile
from jang_app.services.separation_recipe import SeparationRecipe
from jang_app.services.separation_assets import separation_recipe_asset_status
from jang_app.services.settings import (
    RVC_DEVICE_OPTIONS,
    AppSettings,
    RvcSettings,
    StudioLayoutSettings,
    normalize_rvc_device,
    save_app_settings,
)
from jang_app.services.song_assets import (
    REMOVAL_STUDIO_SESSION,
    REMOVAL_VOCAL_OUTPUT,
    REMOVAL_VOCAL_TAKE,
    STAGE_STUDIO,
    SongAsset,
)
from jang_app.services.song_library import SongItem, SongLibrary, SongVocalVersion, sort_song_items
from jang_app.services.song_metadata import build_song_display_metadata
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import StudioSession, StudioTrackState
from jang_app.services.studio_timeline import session_duration_ms, set_studio_track_mix
from jang_app.services.update_polling import UpdateCheckOutcome, UpdatePollingPolicy
from jang_app.services.update_cache import (
    discard_completed_update,
    mark_update_cleanup_ready,
)
from jang_app.services.video_source import VideoSource
from jang_app.services.vocal_project import VocalConversionSettings, VocalProject
from jang_app.services.vocal_project_store import VocalProjectStore
from jang_app.services.workspace_playback import (
    WorkspacePlaybackScope,
    scope_label,
    scope_track_ids,
)
from jang_app.services.work_scope import WorkTaskScope
from jang_app.services.work_convert import WorkConvertSession
from jang_app.services.work_output import WorkOutputSession
from jang_app.services.work_song import (
    WorkSongSession,
    WorkSongStore,
    build_work_song_capabilities,
)
from jang_app.services.youtube_download import YouTubeDownloadResult, download_youtube_audio
from jang_app.version import __version__


PAGE_LIBRARY = 0
PAGE_MODELS = 1
PAGE_SEPARATION = 2
PAGE_CONVERSION = 3
PAGE_STUDIO = 4
PAGE_EXPORT = 5
WORK_SONG_REQUIRED_PAGES = frozenset((PAGE_SEPARATION, PAGE_CONVERSION, PAGE_STUDIO))
GOOGLE_DRIVE_FEATURE = "google_drive_sharing"


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, work_song_store: WorkSongStore | None = None) -> None:
        super().__init__()
        self.settings = settings
        self._workspace_shortcut_filter_installed = False
        set_language(settings.language)
        self.library = SongLibrary()
        self.work_song_store = work_song_store or WorkSongStore()
        self.work_song_session = WorkSongSession(self.work_song_store)
        self.work_convert_session = WorkConvertSession()
        self.work_output_session = WorkOutputSession()
        self._work_song_ready = self.work_song_session.ready
        self._work_song_load_worker: TaskWorker | None = None
        self._work_song_loading_id = ""
        self.player = AudioPlayer()
        self.processing_queue = ProcessingQueue(diagnostics=get_job_diagnostics())
        self._workers: list[TaskWorker] = []
        self._logger = get_logger()
        self._update_check_worker: TaskWorker | None = None
        self._update_dialog: UpdateDialog | None = None
        self._downloaded_update: tuple[Path, ...] = ()
        self._downloaded_update_plan: UpdatePlan | None = None
        self._available_update_plan: UpdatePlan | None = None
        self._update_download_error = ""
        self._update_manifest_etag = ""
        self._update_manifest_last_modified = ""
        self._update_polling_policy = UpdatePollingPolicy()
        self._update_polling_enabled = application_updates_enabled() and bool(
            getattr(sys, "frozen", False)
            or os.environ.get("JJZERO_UPDATE_MANIFEST_URL")
        )
        self._action_task_ids: dict[int, str] = {}
        self._song_items_by_id: dict[str, SongItem] = {}
        self.current_song: SongItem | None = self.work_song_session.source_item
        self.current_work_item: SongItem | None = self.work_song_session.item
        self.current_output_set: OutputSoundSet | None = self.work_output_session.sound_set
        self.playback_session = PlaybackSession()
        self.current_playback_queue: PlaybackQueue | None = self.playback_session.queue
        self._playback_position_ms = self.playback_session.position_ms
        self._playback_resume_positions = self.playback_session.resume_positions
        self._library_preview_song_id = ""
        self._export_song_id = ""
        self._processing_queue_drawer_open = False
        self._is_loading_rvc_settings = False
        self._is_loading_studio_session = False
        self._studio_playback_queue_dirty = False
        self._studio_playback_sources: tuple[AudioMixSource, ...] = ()
        self._studio_playback_prepare_worker: TaskWorker | None = None
        self._studio_playback_prepare_generation = 0
        self._studio_playback_prepare_request: (
            tuple[int, str, StudioSession, tuple[AudioMixSource, ...]] | None
        ) = None
        self.vocal_project_store = VocalProjectStore()
        self.model_workspace = RvcModelWorkspace()
        self.studio_session_autosave = StudioSessionAutosave(self.library.save_studio_session, parent=self)
        self.studio_session_autosave.save_failed.connect(self._on_studio_session_save_failed)

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setMinimumSize(1180, 760)
        self.resize(1500, 900)
        self.task_attention = TaskAttentionController(self.processing_queue, self)

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(120)
        self.playback_timer.timeout.connect(self._sync_global_playback_state)

        self._studio_playback_prepare_timer = QTimer(self)
        self._studio_playback_prepare_timer.setSingleShot(True)
        self._studio_playback_prepare_timer.setInterval(50)
        self._studio_playback_prepare_timer.timeout.connect(self._start_studio_playback_prepare)

        self.update_poll_timer = QTimer(self)
        self.update_poll_timer.setSingleShot(True)
        self.update_poll_timer.timeout.connect(self._start_update_check)

        self._build_ui()
        self._sync_work_song_navigation()
        self.google_drive = GoogleDriveController(
            self,
            paths=APP_PATHS,
            oauth_asset=GOOGLE_OAUTH_CLIENT_PATH,
            model_workspace=self.model_workspace,
            run_worker=self._run_worker,
            model_status=self.model_workspace_page.show_status,
            models_imported=self._on_drive_models_imported,
            logger=self._logger,
        )
        self.google_account_button.connect_requested.connect(
            self.google_drive.connect_account
        )
        self.google_account_button.switch_requested.connect(
            self.google_drive.switch_account
        )
        self.google_account_button.disconnect_requested.connect(
            self.google_drive.disconnect_account
        )
        self.google_drive.account_changed.connect(self.google_account_button.set_account)
        self.google_drive.quota_changed.connect(self.google_account_button.set_quota)
        self.google_drive.account_busy_changed.connect(self.google_account_button.set_running)
        self.google_drive.account_error.connect(self.google_account_button.set_error)
        self.google_drive.account_unavailable.connect(
            self.google_account_button.set_unavailable
        )
        self.google_drive.feature_availability_changed.connect(
            self._set_google_drive_entry_points_enabled
        )
        self.google_drive.share_started.connect(self._on_drive_share_started)
        self.google_drive.share_progress.connect(self._on_drive_share_progress)
        self.google_drive.share_succeeded.connect(self._on_drive_share_succeeded)
        self.google_drive.share_failed.connect(self._on_drive_share_failed)
        self.google_drive.share_deleted.connect(self._on_drive_share_deleted)
        self.model_workspace_page.set_share_status_provider(
            self.google_drive.is_model_shared
        )
        self.model_workspace_page.set_work_share_status_provider(
            self.google_drive.is_model_work_shared
        )
        self.export_page.set_share_status_provider(
            self.google_drive.is_export_shared
        )
        self.google_drive.refresh_account_state()
        self._apply_theme()
        self._apply_language()
        self._refresh_song_list()
        self._refresh_rvc_choices()
        self._refresh_output_sets()
        self._restore_work_song()
        application = QApplication.instance()
        if application is not None:
            application.applicationStateChanged.connect(self._on_application_state_changed)
            application.installEventFilter(self)
            self._workspace_shortcut_filter_installed = True
        if self._update_polling_enabled:
            self.update_poll_timer.start(2500)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.update_poll_timer.stop()
        self._studio_playback_prepare_timer.stop()
        if hasattr(self, "studio_layout_save_timer"):
            self.studio_layout_save_timer.stop()
            self._save_studio_layout()
        self.google_drive.shutdown()
        self.task_attention.close()
        self.studio_session_autosave.flush()
        self.model_workspace_page.stop_preview()
        self.model_workspace_page.shutdown_training()
        self.player.stop()
        self.video_preview_panel.stop()
        application = QApplication.instance()
        if application is not None and self._workspace_shortcut_filter_installed:
            application.removeEventFilter(self)
            self._workspace_shortcut_filter_installed = False
        super().closeEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.KeyPress
            and not event.isAutoRepeat()
            and self.isVisible()
        ):
            application = QApplication.instance()
            active_window = application.activeWindow() if application is not None else None
            if active_window is None or active_window is self:
                focus = application.focusWidget() if application is not None else None
                page_index = self.page_stack.currentIndex()
                has_modal = bool(application and application.activeModalWidget())
                has_popup = bool(application and application.activePopupWidget())
                if (
                    event.key() == Qt.Key.Key_Space
                    and event.modifiers() == Qt.KeyboardModifier.NoModifier
                    and self._workspace_space_shortcut_allowed(
                        page_index,
                        focus,
                        has_modal=has_modal,
                        has_popup=has_popup,
                    )
                ):
                    self._toggle_global_playback()
                    event.accept()
                    return True
                if (
                    event.modifiers() == Qt.KeyboardModifier.ControlModifier
                    and event.key() in {Qt.Key.Key_Z, Qt.Key.Key_Y}
                    and self._studio_history_shortcut_allowed(
                        page_index,
                        focus,
                        has_modal=has_modal,
                        has_popup=has_popup,
                    )
                ):
                    if event.key() == Qt.Key.Key_Z:
                        self.studio_editor.undo()
                    else:
                        self.studio_editor.redo()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _workspace_space_shortcut_allowed(
        page_index: int,
        focus_widget: QWidget | None,
        *,
        has_modal: bool,
        has_popup: bool,
    ) -> bool:
        if page_index not in {PAGE_SEPARATION, PAGE_CONVERSION, PAGE_STUDIO}:
            return False
        return MainWindow._workspace_shortcut_focus_allowed(
            focus_widget,
            has_modal=has_modal,
            has_popup=has_popup,
        )

    @staticmethod
    def _studio_history_shortcut_allowed(
        page_index: int,
        focus_widget: QWidget | None,
        *,
        has_modal: bool,
        has_popup: bool,
    ) -> bool:
        if page_index != PAGE_STUDIO:
            return False
        return MainWindow._workspace_shortcut_focus_allowed(
            focus_widget,
            has_modal=has_modal,
            has_popup=has_popup,
        )

    @staticmethod
    def _workspace_shortcut_focus_allowed(
        focus_widget: QWidget | None,
        *,
        has_modal: bool,
        has_popup: bool,
    ) -> bool:
        if has_modal or has_popup:
            return False
        return not isinstance(
            focus_widget,
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox),
        )

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_window_chrome_state()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_window_chrome_state()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_update_status()
        self._position_processing_queue()
        self._position_size_grip()
        if self.isVisible() and not self.isMaximized():
            apply_window_corner_style(self, rounded=True)

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
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
        self.page_stack.addWidget(self._build_separation_page())
        self.page_stack.addWidget(self._build_conversion_page())
        self.page_stack.addWidget(self._build_studio_page())
        self.page_stack.addWidget(self._build_export_page())

        content_widget = QWidget()
        content_widget.setObjectName("AppContent")
        self._content_widget = content_widget
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(12)
        content_layout.addWidget(self.page_stack, 1)

        self.update_status_button = UpdateStatusButton(content_widget)
        self.update_status_button.clicked.connect(self._open_available_update)

        self.processing_queue_panel = ProcessingQueuePanel(self.processing_queue, content_widget)
        self.processing_queue_panel.geometry_changed.connect(self._position_processing_queue)
        self.processing_queue_panel.log_requested.connect(self._open_log_drawer)
        self.processing_queue_panel.close_requested.connect(self._close_processing_queue_drawer)
        self.processing_queue_panel.hide()

        self.toast_stack = ToastStack(self.processing_queue, content_widget)
        self.toast_stack.geometry_changed.connect(self._position_processing_queue)
        self.toast_stack.details_requested.connect(self._open_log_drawer)

        self.log_drawer = LogDrawer(self.processing_queue, content_widget)
        self.log_drawer.close_requested.connect(self._close_log_drawer)
        self.log_drawer.queue_requested.connect(self._open_processing_queue_drawer)
        self.log_drawer.open_location_requested.connect(self._open_log_location)
        QTimer.singleShot(0, self._position_update_status)
        QTimer.singleShot(0, self._position_processing_queue)

        root_layout.addWidget(content_widget, 1)

        self.setCentralWidget(root_widget)
        self.size_grip = QSizeGrip(root_widget)
        self.size_grip.raise_()
        QTimer.singleShot(0, self._position_size_grip)

    def _build_top_bar(self) -> QWidget:
        self.title_bar = WindowTitleBar(
            APP_NAME,
            APP_ICON_PATH,
            version_text=f"v{__version__}",
        )
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
                ("Separation", PAGE_SEPARATION),
                ("Conversion", PAGE_CONVERSION),
                ("Studio", PAGE_STUDIO),
            ),
            ("Export", PAGE_EXPORT),
        )
        self.primary_navigation.page_requested.connect(self._navigate_to_page)
        self.primary_navigation.settings_requested.connect(self._open_system_setup)
        self.primary_navigation.work_song_changed.connect(
            self._on_navigation_work_song_changed
        )

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
        self.google_account_button = GoogleAccountButton(GOOGLE_ICON_PATH)
        self.processing_queue_button = ProcessingQueueButton(
            self.processing_queue,
            parent=self.title_bar.action_widget,
        )
        self.processing_queue_button.clicked.connect(self._toggle_processing_queue_drawer)
        self.settings_button = self.primary_navigation.settings_button
        set_translated_tooltip(self.settings_button, "System setup")
        self.title_bar.add_action_widget(self.processing_queue_button)
        self.title_bar.add_action_widget(self.google_account_button)
        self.title_bar.add_action_widget(self.language_button)
        self.title_bar.add_action_widget(self.theme_button)

        return self.primary_navigation

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        import_panel = QFrame()
        import_panel.setObjectName("Panel")
        import_panel.setMinimumWidth(360)
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
        self.library_sort_combo = ScrollSafeComboBox()
        self.library_sort_combo.setFixedWidth(150)
        set_translated_tooltip(self.library_sort_combo, "Sort songs")
        self.library_sort_combo.currentIndexChanged.connect(lambda _index: self._refresh_song_list())
        filter_layout.addWidget(self.library_search_edit, 1)
        filter_layout.addWidget(self.library_sort_combo, 0)

        self.song_list = QListWidget()
        self.song_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.song_list.itemDoubleClicked.connect(lambda _item: self._open_selected_library_details())

        list_layout.addLayout(list_header)
        list_layout.addLayout(filter_layout)
        list_layout.addWidget(self.song_list, 1)

        self.library_details_panel = LibraryDetailsPanel()
        self.library_details_panel.back_requested.connect(self._close_library_details)
        self.library_details_panel.open_location_requested.connect(self._open_library_asset_location)
        self.library_details_panel.remove_asset_requested.connect(self._remove_library_asset)
        self.library_details_panel.remove_assets_requested.connect(self._remove_library_assets)
        self.library_details_panel.preview_requested.connect(
            self._toggle_library_asset_preview
        )
        self.library_details_panel.preview_play_toggled.connect(
            self._toggle_library_asset_preview_playback
        )
        self.library_details_panel.preview_seek_requested.connect(
            self._seek_library_asset_preview
        )

        self.library_content_stack = QStackedWidget()
        self.library_content_stack.addWidget(list_panel)
        self.library_content_stack.addWidget(self.library_details_panel)
        self._populate_library_sort_combo()

        self.library_splitter = create_workspace_splitter(
            (import_panel, self.library_content_stack),
            object_name="LibraryWorkspaceSplitter",
            sizes=(390, 1210),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        layout.addWidget(self.library_splitter, 1)
        return page

    def _build_separation_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(380)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(16)

        left_layout.addWidget(self._build_separate_step_page(), 1)

        self.separation_results_panel = VocalResultsPanel(mode="separation")
        self.separation_stem_pool = SeparationStemPoolPanel()
        self.separation_stem_pool.selection_changed.connect(
            self._on_separation_stem_selection_changed
        )
        self.separation_results_panel.open_location_requested.connect(
            self._open_vocal_output_location
        )
        self.separation_results_panel.seek_requested.connect(self._seek_output_playback)
        self.separation_results_panel.playback_settings_changed.connect(
            self._on_result_playback_settings_changed
        )

        self.separation_results_splitter = create_workspace_splitter(
            (self.separation_stem_pool, self.separation_results_panel),
            object_name="SeparationResultsSplitter",
            sizes=(320, 890),
            stretch_factors=(0, 1),
            collapsible=(True, True),
        )
        self.separation_transport_bar = ResultTransportBar()
        self.separation_transport_bar.play_toggled.connect(
            self._toggle_global_playback
        )
        self.separation_transport_bar.seek_requested.connect(
            self._seek_global_playback
        )
        separation_results = QWidget()
        separation_results.setObjectName("WorkspaceResultArea")
        separation_results_layout = QVBoxLayout(separation_results)
        separation_results_layout.setContentsMargins(0, 0, 0, 0)
        separation_results_layout.setSpacing(8)
        separation_results_layout.addWidget(self.separation_results_splitter, 1)
        separation_results_layout.addWidget(self.separation_transport_bar, 0)

        self.separation_splitter = create_workspace_splitter(
            (left_panel, separation_results),
            object_name="SeparationWorkspaceSplitter",
            sizes=(390, 1210),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        layout.addWidget(self.separation_splitter, 1)
        return page

    def _build_conversion_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(380)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(16)
        left_layout.addWidget(self._build_convert_step_page(), 1)

        self.vocal_results_panel = VocalResultsPanel(mode="conversion")
        self.vocal_results_panel.converted_selected.connect(self._activate_vocal_converted_version)
        self.vocal_results_panel.open_location_requested.connect(self._open_vocal_output_location)
        self.vocal_results_panel.open_take_requested.connect(self._open_vocal_take_location)
        self.vocal_results_panel.rename_take_requested.connect(self._rename_vocal_take)
        self.vocal_results_panel.remove_take_requested.connect(self._remove_vocal_take)
        self.vocal_results_panel.reconvert_take_requested.connect(self._reconvert_vocal_take)
        self.vocal_results_panel.seek_requested.connect(self._seek_output_playback)
        self.vocal_results_panel.playback_settings_changed.connect(
            self._on_result_playback_settings_changed
        )

        self.conversion_result_browser = ConversionResultBrowser()
        self.conversion_result_browser.converted_selected.connect(
            self._activate_vocal_converted_version
        )

        self.conversion_results_splitter = create_workspace_splitter(
            (self.conversion_result_browser, self.vocal_results_panel),
            object_name="ConversionResultsSplitter",
            sizes=(320, 880),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        self.conversion_transport_bar = ResultTransportBar()
        self.conversion_transport_bar.play_toggled.connect(
            self._toggle_global_playback
        )
        self.conversion_transport_bar.seek_requested.connect(
            self._seek_global_playback
        )
        conversion_results = QWidget()
        conversion_results.setObjectName("WorkspaceResultArea")
        conversion_results_layout = QVBoxLayout(conversion_results)
        conversion_results_layout.setContentsMargins(0, 0, 0, 0)
        conversion_results_layout.setSpacing(8)
        conversion_results_layout.addWidget(self.conversion_results_splitter, 1)
        conversion_results_layout.addWidget(self.conversion_transport_bar, 0)

        self.conversion_splitter = create_workspace_splitter(
            (left_panel, conversion_results),
            object_name="ConversionWorkspaceSplitter",
            sizes=(400, 1200),
            stretch_factors=(0, 1),
            collapsible=(True, False),
        )
        layout.addWidget(self.conversion_splitter, 1)
        return page

    def _build_studio_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.video_preview_panel = VideoPreviewPanel()
        self.video_preview_panel.browse_requested.connect(self._choose_video_file)
        self.video_preview_panel.files_dropped.connect(self._attach_video_files)
        self.video_preview_panel.url_requested.connect(self._attach_video_url)
        self.video_preview_panel.open_location_requested.connect(self._open_video_location)
        self.video_preview_panel.clear_requested.connect(self._clear_video_source)
        self.video_preview_panel.download_requested.connect(self._start_video_download)
        self.video_preview_panel.saved_source_requested.connect(self._select_saved_video_source)
        self.video_preview_panel.set_compact_mode(True)
        self.studio_editor = StudioEditor(include_sidebars=False)
        self.studio_editor.session_committed.connect(self._on_studio_editor_session_changed)
        self.studio_editor.asset_remove_requested.connect(self._remove_studio_pool_asset)
        self.studio_editor.seek_requested.connect(self._seek_studio_timeline)
        self.studio_editor.open_location_requested.connect(self._open_track_location)
        self.studio_transport_bar = StudioTransportBar()
        self.studio_transport_bar.play_toggled.connect(self._toggle_global_playback)
        self.studio_transport_bar.seek_requested.connect(self._seek_studio_timeline)
        self.studio_transport_bar.zoom_changed.connect(self.studio_editor.set_zoom)
        self.studio_transport_bar.split_mode_changed.connect(
            self.studio_editor.set_split_mode
        )
        self.studio_editor.split_mode_changed.connect(
            self.studio_transport_bar.set_split_mode
        )
        self.studio_editor.split_tool_available_changed.connect(
            self.studio_transport_bar.set_split_enabled
        )
        self.studio_transport_bar.undo_requested.connect(self.studio_editor.undo)
        self.studio_transport_bar.redo_requested.connect(self.studio_editor.redo)
        self.studio_editor.history_availability_changed.connect(
            self.studio_transport_bar.set_history_available
        )

        studio_preview_area = QWidget()
        studio_preview_area.setObjectName("StudioPreviewArea")
        studio_preview_layout = QVBoxLayout(studio_preview_area)
        studio_preview_layout.setContentsMargins(0, 0, 0, 0)
        studio_preview_layout.setSpacing(8)
        studio_preview_layout.addWidget(self.video_preview_panel, 1)
        studio_preview_layout.addWidget(self.studio_transport_bar, 0)

        self.studio_center_splitter = create_workspace_splitter(
            (studio_preview_area, self.studio_editor),
            object_name="StudioCenterSplitter",
            orientation=Qt.Orientation.Vertical,
            sizes=self.settings.studio_layout.center_sizes,
            stretch_factors=(45, 55),
        )

        self.studio_workspace_splitter = create_workspace_splitter(
            (
                self.studio_editor.left_sidebar,
                self.studio_center_splitter,
                self.studio_editor.inspector_scroll,
            ),
            object_name="StudioWorkspaceSplitter",
            sizes=self.settings.studio_layout.workspace_sizes,
            stretch_factors=(0, 1, 0),
            collapsible=(True, False, True),
        )

        self.studio_layout_save_timer = QTimer(self)
        self.studio_left_splitter = self.studio_editor.left_sidebar
        self.studio_left_splitter.setSizes(list(self.settings.studio_layout.left_sizes))
        self.studio_layout_save_timer.setSingleShot(True)
        self.studio_layout_save_timer.setInterval(350)
        self.studio_layout_save_timer.timeout.connect(self._save_studio_layout)
        self.studio_workspace_splitter.splitterMoved.connect(
            self._queue_studio_layout_save
        )
        self.studio_center_splitter.splitterMoved.connect(
            self._queue_studio_layout_save
        )
        self.studio_left_splitter.splitterMoved.connect(
            self._queue_studio_layout_save
        )

        # The old rows remain parented and hidden while Separation and Conversion
        # still use them as their shared playback controls.
        self.studio_output_panel = self._build_output_panel()
        self.studio_output_panel.setParent(page)
        self.studio_output_panel.hide()

        layout.addWidget(self.studio_workspace_splitter, 1)
        return page

    def _queue_studio_layout_save(self, *_args) -> None:
        self.studio_layout_save_timer.start()

    def _save_studio_layout(self) -> None:
        workspace_sizes = tuple(self.studio_workspace_splitter.sizes())
        center_sizes = tuple(self.studio_center_splitter.sizes())
        left_sizes = tuple(self.studio_left_splitter.sizes())
        if len(workspace_sizes) != 3 or len(center_sizes) != 2 or len(left_sizes) != 2:
            return
        if sum(workspace_sizes) <= 0 or sum(center_sizes) <= 0 or sum(left_sizes) <= 0:
            return
        studio_layout = StudioLayoutSettings(
            workspace_sizes=workspace_sizes,
            center_sizes=center_sizes,
            left_sizes=left_sizes,
        )
        if studio_layout == self.settings.studio_layout:
            return
        self.settings = replace(self.settings, studio_layout=studio_layout)
        save_app_settings(self.settings)

    def _build_export_page(self) -> QWidget:
        self.export_page = ExportPage()
        self.export_page.song_changed.connect(self._on_export_song_changed)
        self.export_page.audio_export_requested.connect(self._start_audio_mix_export)
        self.export_page.video_export_requested.connect(self._start_video_render)
        self.export_page.open_location_requested.connect(self._open_export_location)
        self.export_page.share_requested.connect(self._open_export_drive_share)
        self.export_page.delete_share_requested.connect(
            self._delete_export_drive_share
        )
        self.export_page.preview_requested.connect(self._toggle_export_preview)
        self.export_page.preview_play_toggled.connect(
            self._toggle_export_preview_playback
        )
        self.export_page.preview_seek_requested.connect(self._seek_export_preview)
        self.export_page.rename_requested.connect(self._rename_export)
        return self.export_page

    def _build_models_page(self) -> QWidget:
        hardware_selection = recorded_hardware_selection(APP_PATHS)
        self.model_workspace_page = ModelWorkspacePage(
            self.settings.rvc.root,
            workspace=self.model_workspace,
            processing_queue=self.processing_queue,
            execution_runtime_root=RVC_RUNTIME_DIR,
            runtime_profile=(
                hardware_selection.profile
                if hardware_selection is not None
                else ""
            ),
            hardware_selection=hardware_selection,
        )
        self.model_workspace_page.use_in_convert_requested.connect(self._use_model_in_convert)
        self.model_workspace_page.open_location_requested.connect(self._open_model_location)
        self.model_workspace_page.preview_started.connect(self._on_model_preview_started)
        self.model_workspace_page.log_requested.connect(self._open_log_drawer)
        self.model_workspace_page.system_setup_requested.connect(
            self._open_system_setup
        )
        self.model_workspace_page.models_changed.connect(self._refresh_rvc_choices)
        self.model_workspace_page.share_requested.connect(self._open_model_drive_share)
        self.model_workspace_page.delete_share_requested.connect(
            self._delete_model_drive_share
        )
        self.model_workspace_page.work_share_requested.connect(
            self._open_model_work_drive_share
        )
        self.model_workspace_page.delete_work_share_requested.connect(
            self._delete_model_work_drive_share
        )
        self.model_workspace_page.drive_import_requested.connect(
            self._start_drive_model_import
        )
        return self.model_workspace_page

    def _build_separate_step_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("Card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel("Separate")
        title.setObjectName("SectionTitle")

        self.separation_recipe_selector = SeparationRecipeSelector()

        self.separation_action = TaskActionWidget("Separation", "Separate")
        self.separation_action.triggered.connect(self._start_separation)
        self.separation_action.set_action_enabled(False)

        layout.addWidget(title)
        layout.addWidget(self.separation_recipe_selector)
        layout.addWidget(self.separation_action)
        layout.addStretch(1)
        return page

    def _build_convert_step_page(self) -> QWidget:
        rvc_panel = QFrame()
        rvc_panel.setObjectName("Card")
        rvc_layout = QVBoxLayout(rvc_panel)
        rvc_layout.setContentsMargins(22, 22, 22, 22)
        rvc_layout.setSpacing(12)
        rvc_title = QLabel("RVC Convert")
        rvc_title.setObjectName("SectionTitle")

        self.rvc_settings_scroll = QScrollArea()
        self.rvc_settings_scroll.setObjectName("RvcSettingsScroll")
        self.rvc_settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.rvc_settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        rvc_settings_content = TransparentContainer(
            object_name="RvcSettingsScrollContent"
        )
        rvc_settings_layout = QVBoxLayout(rvc_settings_content)
        rvc_settings_layout.setContentsMargins(0, 0, 6, 0)
        rvc_settings_layout.setSpacing(14)

        self.conversion_input_pool = VocalVersionPool(
            "vocal",
            title_key="Conversion Input",
        )
        self.conversion_input_pool.setProperty("poolContext", "conversionInput")
        self.conversion_input_pool.selection_changed.connect(
            self._on_conversion_input_version_changed
        )
        self.conversion_input_pool.setMinimumHeight(190)
        self.conversion_input_pool.setMaximumHeight(300)

        self.rvc_settings_frame = QFrame()
        self.rvc_settings_frame.setObjectName("InsetCard")
        settings_layout = QVBoxLayout(self.rvc_settings_frame)
        settings_layout.setContentsMargins(14, 12, 14, 14)
        settings_layout.setSpacing(10)

        self.rvc_settings_header = CollapsibleCardHeader("Model Settings")

        primary_form = QGridLayout()
        primary_form.setContentsMargins(0, 0, 0, 0)
        primary_form.setHorizontalSpacing(8)
        primary_form.setVerticalSpacing(10)

        self.rvc_advanced_settings_panel = QFrame()
        self.rvc_advanced_settings_panel.setObjectName("RvcAdvancedSettingsPanel")
        advanced_form = QGridLayout(self.rvc_advanced_settings_panel)
        advanced_form.setContentsMargins(0, 2, 0, 0)
        advanced_form.setHorizontalSpacing(8)
        advanced_form.setVerticalSpacing(10)
        self.rvc_advanced_settings_panel.hide()
        self.rvc_settings_header.toggled.connect(
            self.rvc_advanced_settings_panel.setVisible
        )

        self.rvc_root_edit = QLineEdit(str(self.settings.rvc.root))
        self.rvc_root_edit.editingFinished.connect(self._save_rvc_settings_from_controls)
        self.browse_rvc_button = SvgIconButton("folder", size=34)
        self.browse_rvc_button.setObjectName("ControlIconButton")
        self.browse_rvc_button.setToolTip("Select RVC root")
        self.browse_rvc_button.clicked.connect(self._choose_rvc_root)

        self.model_combo = ScrollSafeComboBox()
        self.model_combo.setMinimumWidth(0)
        self.model_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.model_combo.currentIndexChanged.connect(self._on_rvc_model_changed)
        self.index_combo = ScrollSafeComboBox()
        self.index_combo.setMinimumWidth(0)
        self.index_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.index_combo.currentIndexChanged.connect(self._save_rvc_settings_from_controls)
        self.refresh_rvc_button = SvgIconButton("refresh", size=34)
        self.refresh_rvc_button.setObjectName("ControlIconButton")
        self.refresh_rvc_button.setToolTip("Refresh RVC models")
        self.refresh_rvc_button.clicked.connect(self._refresh_rvc_catalog)

        self.pitch_spin = ScrollSafeSpinBox()
        self.pitch_spin.setRange(-999, 999)
        self.pitch_spin.setValue(self.settings.rvc.pitch)
        self.pitch_spin.valueChanged.connect(self._save_rvc_settings_from_controls)

        self.device_combo = ScrollSafeComboBox()
        self.device_combo.setMinimumWidth(0)
        self.device_combo.addItems(list(RVC_DEVICE_OPTIONS))
        selected_device = normalize_rvc_device(self.settings.rvc.device)
        self.device_combo.setCurrentText(selected_device)
        self.device_combo.currentIndexChanged.connect(self._save_rvc_settings_from_controls)

        self.rvc_root_edit.setMinimumWidth(0)
        self.rvc_root_edit.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )

        self.rvc_inference_controls = RvcInferenceControls(self.settings.rvc.inference)
        self.rvc_inference_controls.settings_changed.connect(
            self._on_rvc_inference_settings_changed
        )

        primary_form.addWidget(_field_label("Model"), 0, 0)
        primary_form.addWidget(self.model_combo, 0, 1)
        primary_form.addWidget(self.refresh_rvc_button, 0, 2)
        primary_form.addWidget(_field_label("Pitch"), 1, 0)
        primary_form.addWidget(self.pitch_spin, 1, 1)

        advanced_form.addWidget(_field_label("Root"), 0, 0)
        advanced_form.addWidget(self.rvc_root_edit, 0, 1)
        advanced_form.addWidget(self.browse_rvc_button, 0, 2)
        advanced_form.addWidget(_field_label("Index"), 1, 0)
        advanced_form.addWidget(self.index_combo, 1, 1, 1, 2)
        advanced_form.addWidget(_field_label("Device"), 2, 0)
        advanced_form.addWidget(self.device_combo, 2, 1)

        settings_layout.addWidget(self.rvc_settings_header)
        settings_layout.addLayout(primary_form)
        settings_layout.addWidget(self.rvc_advanced_settings_panel)

        self.rvc_action = TaskActionWidget("Convert Vocal", "Convert")
        self.rvc_action.triggered.connect(self._start_rvc_conversion)
        self.rvc_action.set_action_enabled(False)
        self.rvc_action.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        rvc_settings_layout.addWidget(self.conversion_input_pool)
        rvc_settings_layout.addWidget(self.rvc_settings_frame)
        rvc_settings_layout.addWidget(self.rvc_inference_controls)
        rvc_settings_layout.addStretch(1)
        attach_transparent_scroll_widget(
            self.rvc_settings_scroll,
            rvc_settings_content,
        )

        rvc_layout.addWidget(rvc_title, 0)
        rvc_layout.addWidget(self.rvc_settings_scroll, 1)
        rvc_layout.addWidget(self.rvc_action, 0)
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
        track_scroll.setObjectName("StudioOutputScroll")
        track_content = TransparentContainer(object_name="StudioOutputTrackContent")
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
        attach_transparent_scroll_widget(track_scroll, track_content)

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
        for transport_name in (
            "separation_transport_bar",
            "conversion_transport_bar",
        ):
            transport = getattr(self, transport_name, None)
            if transport is not None:
                transport.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "update_status_button"):
            self.update_status_button.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "processing_queue_panel"):
            self.processing_queue_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "processing_queue_button"):
            self.processing_queue_button.set_theme_mode(self.settings.theme_mode)
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
        if hasattr(self, "separation_results_panel"):
            self.separation_results_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "separation_stem_pool"):
            self.separation_stem_pool.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "conversion_input_pool"):
            self.conversion_input_pool.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "rvc_inference_controls"):
            self.rvc_inference_controls.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "rvc_settings_header"):
            self.rvc_settings_header.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "conversion_result_browser"):
            self.conversion_result_browser.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "vocal_results_panel"):
            self.vocal_results_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "library_details_panel"):
            self.library_details_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "export_page"):
            self.export_page.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "video_preview_panel"):
            self.video_preview_panel.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "studio_editor"):
            self.studio_editor.set_theme_mode(self.settings.theme_mode)
        if hasattr(self, "studio_transport_bar"):
            self.studio_transport_bar.set_theme_mode(self.settings.theme_mode)
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
        self.google_account_button.apply_language()
        self.primary_navigation.apply_language()
        for language, action in self.language_actions.items():
            action.setChecked(language == self.settings.language)
        self.separation_transport_bar.apply_language()
        self.conversion_transport_bar.apply_language()
        self.update_status_button.apply_language()
        self.processing_queue_panel.apply_language()
        self.processing_queue_button.apply_language()
        self.toast_stack.apply_language()
        self.log_drawer.apply_language()
        self.model_workspace_page.apply_language()
        self.separation_results_panel.apply_language()
        self.separation_stem_pool.apply_language()
        self.conversion_input_pool.apply_language()
        self.rvc_inference_controls.apply_language()
        self.rvc_settings_header.apply_language()
        self.vocal_results_panel.apply_language()
        self.conversion_result_browser.apply_language()
        self.library_details_panel.apply_language()
        self.export_page.apply_language()
        self.video_preview_panel.apply_language()
        self.studio_editor.apply_language()
        self.studio_transport_bar.apply_language()
        self.separation_recipe_selector.apply_language()
        self._populate_library_sort_combo()
        set_translated_tooltip(self.library_sort_combo, "Sort songs")

        if hasattr(self, "song_list"):
            self._sync_work_song_rows()
        self._sync_work_song_navigation()

    def _position_update_status(self) -> None:
        if not hasattr(self, "update_status_button"):
            return
        button = self.update_status_button
        if not button.isVisible():
            return
        button.move(
            *update_button_position(
                self._content_widget.height(),
                button.height(),
                anchor_tops=(),
            )
        )
        button.raise_()

    def _sync_playback_surfaces(self) -> None:
        position_update_status = getattr(self, "_position_update_status", None)
        if callable(position_update_status):
            position_update_status()
        self._position_processing_queue()

    def _result_transport_for_scope(
        self,
        scope: WorkspacePlaybackScope | None,
    ) -> ResultTransportBar | None:
        return {
            WorkspacePlaybackScope.SEPARATION: getattr(
                self, "separation_transport_bar", None
            ),
            WorkspacePlaybackScope.CONVERSION: getattr(
                self, "conversion_transport_bar", None
            ),
        }.get(scope)

    def _clear_result_transports(
        self,
        *,
        except_transport: ResultTransportBar | None = None,
    ) -> None:
        for transport_name in (
            "separation_transport_bar",
            "conversion_transport_bar",
        ):
            transport = getattr(self, transport_name, None)
            if transport is not None and transport is not except_transport:
                transport.clear()

    def _position_processing_queue(self) -> None:
        if not hasattr(self, "processing_queue_panel"):
            return
        panel = self.processing_queue_panel
        parent = self._content_widget
        player_top = parent.height() - 16
        drawer_open = hasattr(self, "log_drawer") and self.log_drawer.isVisible()
        queue_open = self._processing_queue_drawer_open

        if drawer_open:
            drawer = self.log_drawer
            top_position = 16
            drawer.setFixedHeight(max(260, player_top - top_position - 10))
            self._move_content_overlay(
                drawer,
                max(16, parent.width() - drawer.width() - 16),
                top_position,
            )
            drawer.raise_()
            panel.hide()
        elif queue_open:
            panel.show()
            top_position = 16
            panel.setFixedHeight(max(260, player_top - top_position - 10))
            x_position = max(16, parent.width() - panel.width() - 16)
            self._move_content_overlay(panel, x_position, top_position)
            panel.raise_()
        else:
            panel.hide()

        if hasattr(self, "toast_stack") and self.toast_stack.isVisible():
            toast = self.toast_stack
            if drawer_open:
                toast_x = max(16, self.log_drawer.x() - toast.width() - 10)
                toast_y = max(16, player_top - toast.height() - 10)
            elif queue_open:
                toast_x = max(16, panel.x() - toast.width() - 10)
                toast_y = max(16, player_top - toast.height() - 10)
            else:
                toast_x = max(16, parent.width() - toast.width() - 16)
                toast_y = max(16, player_top - toast.height() - 10)
            toast.move(toast_x, toast_y)
            toast.raise_()

    def _move_content_overlay(self, widget: QWidget, x: int, y: int) -> None:
        position = QPoint(x, y)
        if widget.isWindow():
            position = self._content_widget.mapToGlobal(position)
        widget.move(position)

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
        self._processing_queue_drawer_open = False
        self.processing_queue_button.setChecked(False)
        self.processing_queue_button.apply_language()
        self.processing_queue_panel.hide()
        self.log_drawer.show()
        self.log_drawer.refresh_content()
        if task_id:
            self.log_drawer.select_task(task_id)
        self._position_processing_queue()

    def _close_log_drawer(self) -> None:
        self.log_drawer.hide()
        self._position_processing_queue()

    def _toggle_processing_queue_drawer(self, *_args) -> None:
        if self._processing_queue_drawer_open:
            self._close_processing_queue_drawer()
        else:
            self._open_processing_queue_drawer()

    def _open_processing_queue_drawer(self) -> None:
        self._processing_queue_drawer_open = True
        self.log_drawer.hide()
        self.processing_queue_button.setChecked(True)
        self.processing_queue_button.apply_language()
        self.processing_queue_panel.show()
        self._position_processing_queue()

    def _close_processing_queue_drawer(self) -> None:
        self._processing_queue_drawer_open = False
        self.processing_queue_button.setChecked(False)
        self.processing_queue_button.apply_language()
        self.processing_queue_panel.hide()
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
        if start_detached_command((sys.executable, *arguments), cwd=Path.cwd()):
            QApplication.quit()

    def _start_update_check(self) -> None:
        if (
            not self._update_polling_enabled
            or self._update_check_worker is not None
            or self._available_update_plan is not None
        ):
            return
        self.update_poll_timer.stop()
        manifest_url = os.environ.get("JJZERO_UPDATE_MANIFEST_URL", DEFAULT_MANIFEST_URL)
        etag = self._update_manifest_etag
        last_modified = self._update_manifest_last_modified
        worker = TaskWorker(
            lambda progress: _check_for_updates(
                manifest_url,
                progress,
                etag=etag,
                last_modified=last_modified,
            )
        )
        self._update_check_worker = worker
        self._workers.append(worker)

        def complete(result: object) -> None:
            self._update_polling_policy.record_success(monotonic())
            if not isinstance(result, UpdateCheckOutcome):
                return
            self._update_manifest_etag = result.etag
            self._update_manifest_last_modified = result.last_modified
            plan = result.plan
            if plan is not None:
                self._apply_release_feature_policy(plan.release)
            if plan is not None and plan.required:
                self._available_update_plan = plan
                self.update_status_button.set_available(
                    plan.release.version,
                    runtime_only=not plan.application_required,
                )
                self.update_status_button.show()
                self._position_update_status()
            elif plan is not None:
                self.update_status_button.hide()

        def failed(error: str) -> None:
            self._update_polling_policy.record_failure(monotonic())
            self._logger.info("Automatic update check failed: %s", _last_error_line(error))

        def cleanup() -> None:
            self._update_check_worker = None
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()
            self._schedule_next_update_check()

        worker.succeeded.connect(complete)
        worker.failed.connect(failed)
        worker.finished.connect(cleanup)
        worker.start()

    def _apply_release_feature_policy(self, release: ReleaseManifest) -> None:
        enabled = GOOGLE_DRIVE_FEATURE not in release.disabled_features
        self.google_drive.set_feature_enabled(
            enabled,
            tr("Google Drive sharing is temporarily unavailable."),
        )

    def _set_google_drive_entry_points_enabled(self, is_enabled: bool) -> None:
        self.model_workspace_page.set_sharing_enabled(is_enabled)
        self.export_page.set_sharing_enabled(is_enabled)

    def _schedule_next_update_check(self) -> None:
        if not self._update_polling_enabled or self._available_update_plan is not None:
            self.update_poll_timer.stop()
            return
        delay = self._update_polling_policy.next_delay_ms(
            monotonic(),
            QApplication.applicationState() == Qt.ApplicationState.ApplicationActive,
        )
        self.update_poll_timer.start(max(1, delay))

    def _on_application_state_changed(self, state: Qt.ApplicationState) -> None:
        if not self._update_polling_enabled or self._available_update_plan is not None:
            return
        if self._update_polling_policy.last_checked_at is None:
            return
        if (
            state == Qt.ApplicationState.ApplicationActive
            and self._update_polling_policy.should_check_on_activation(monotonic())
        ):
            self.update_poll_timer.start(1)
            return
        self._schedule_next_update_check()

    def _open_available_update(self) -> None:
        if self._available_update_plan is not None:
            self._show_update_dialog(self._available_update_plan)

    def _show_update_dialog(self, plan: UpdatePlan) -> None:
        if self._update_dialog is not None:
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return
        dialog = UpdateDialog(
            plan,
            APP_ICON_PATH,
            current_version=__version__,
            theme_mode=self.settings.theme_mode,
            parent=self,
        )
        self._update_dialog = dialog
        dialog.download_requested.connect(lambda: self._start_update_download(plan))
        dialog.install_requested.connect(self._install_downloaded_update)
        dialog.finished.connect(lambda _result: self._clear_update_dialog(dialog))
        if self.update_status_button.state == STATE_READY and self._downloaded_update:
            dialog.set_ready_to_install()
        elif self.update_status_button.state == STATE_FAILED:
            dialog.set_download_failed(
                self._update_download_error or tr("The update installer is unavailable.")
            )
        dialog.show()

    def _clear_update_dialog(self, dialog: UpdateDialog) -> None:
        if self._update_dialog is dialog:
            self._update_dialog = None
        dialog.deleteLater()

    def _start_update_download(self, plan: UpdatePlan) -> None:
        dialog = self._update_dialog
        if dialog is None:
            return
        dialog.set_downloading()
        self._update_download_error = ""
        self.update_status_button.set_downloading()
        worker = TaskWorker(
            lambda progress: _download_update_artifacts(plan, APP_PATHS.cache_dir, progress)
        )

        def succeeded(result: object) -> None:
            paths = (
                tuple(path for path in result if isinstance(path, Path))
                if isinstance(result, tuple)
                else ()
            )
            self._downloaded_update = paths
            self._downloaded_update_plan = plan
            if not paths:
                self._set_update_download_failed(
                    dialog,
                    tr("No update installer was downloaded."),
                )
                return
            dialog.set_ready_to_install()
            self.update_status_button.set_ready()

        def failed(error: str) -> None:
            self._set_update_download_failed(dialog, _last_error_line(error))

        worker.progress_changed.connect(self.update_status_button.set_progress)

        self._run_worker(
            worker,
            succeeded,
            failed,
            dialog,
            task_title="Download Update",
            task_detail=f"JJZero Audio {plan.release.version}",
        )

    def _set_update_download_failed(self, dialog: UpdateDialog, error: str) -> None:
        self._update_download_error = error
        self.update_status_button.set_failed()
        dialog.set_download_failed(error)

    def _install_downloaded_update(self) -> None:
        plan = self._downloaded_update_plan
        if plan is None:
            return
        runtime_packages = tuple(
            path for path in self._downloaded_update if path.suffix.lower() == ".zip"
        )
        if plan.runtime_required or plan.rvc_profile_required:
            if not runtime_packages:
                if self._update_dialog is not None:
                    self._set_update_download_failed(
                        self._update_dialog,
                        tr("AI runtime packages are unavailable."),
                    )
                return
            self.player.stop()
            self.video_preview_panel.stop()
            dialog = self._update_dialog
            if dialog is None:
                return
            dialog.set_installing_runtime()
            worker = TaskWorker(
                lambda progress: install_update_runtime_components(
                    plan,
                    self._downloaded_update,
                    APP_PATHS.runtime_root,
                    progress=progress,
                )
            )
            self._run_worker(
                worker,
                lambda _result: self._finish_runtime_update_install(plan),
                lambda error: self._set_update_download_failed(
                    dialog,
                    _last_error_line(error),
                ),
                dialog,
                task_title="Install AI Runtime",
                task_detail=(
                    f"RVC {plan.rvc_profile}"
                    if plan.rvc_profile_required and not plan.runtime_required
                    else f"Runtime {plan.release.ai_runtime.version if plan.release.ai_runtime else ''}"
                ),
            )
            return
        self._launch_downloaded_installer_or_restart()

    def _finish_runtime_update_install(self, plan: UpdatePlan) -> None:
        runtime_names = {artifact.name for artifact in plan.runtime_artifacts}
        runtime_packages = tuple(
            path for path in self._downloaded_update if path.name in runtime_names
        )
        if plan.application_required:
            discard_cached_artifacts(runtime_packages, APP_PATHS.cache_dir)
        elif runtime_packages:
            report = discard_completed_update(
                APP_PATHS.cache_dir,
                runtime_packages[0].parent,
            )
            if report.failed_paths:
                self._logger.warning(
                    "Runtime update cache cleanup incomplete | failures=%s",
                    len(report.failed_paths),
                )
        self._launch_downloaded_installer_or_restart()

    def _launch_downloaded_installer_or_restart(self) -> None:
        installer = next(
            (path for path in self._downloaded_update if path.suffix.lower() == ".exe"),
            None,
        )
        plan = self._downloaded_update_plan
        if installer is None:
            if plan is not None and not plan.application_required:
                if getattr(sys, "frozen", False):
                    arguments = sys.argv[1:]
                else:
                    arguments = [str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
                if start_detached_command((sys.executable, *arguments), cwd=Path.cwd()):
                    QApplication.quit()
                    return
            if self._update_dialog is not None:
                self._set_update_download_failed(
                    self._update_dialog,
                    tr("The update installer is unavailable."),
                )
            return
        arguments = (
            "/SILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/RUN",
        )
        if not start_detached_command((str(installer), *arguments), cwd=installer.parent):
            if self._update_dialog is not None:
                self._set_update_download_failed(
                    self._update_dialog,
                    tr("Could not start the update installer."),
                )
            return
        if plan is not None and not mark_update_cleanup_ready(
            APP_PATHS.cache_dir,
            installer.parent,
            plan.release.version,
        ):
            self._logger.warning(
                "Application update cache cleanup marker could not be written | version=%s",
                plan.release.version,
            )
        QApplication.quit()

    def _change_language(self, language: str) -> None:
        if language == self.settings.language:
            return
        self.settings = replace(self.settings, language=language)
        save_app_settings(self.settings)
        self._apply_language()

    def _navigate_to_page(self, index: int) -> None:
        if (
            index in WORK_SONG_REQUIRED_PAGES
            and hasattr(self, "current_work_item")
            and self.current_work_item is None
        ):
            self.primary_navigation.set_current_page(self.page_stack.currentIndex())
            return
        previous_index = self.page_stack.currentIndex()
        if previous_index == PAGE_STUDIO and index != PAGE_STUDIO:
            self.studio_session_autosave.flush()
        workspace_pages = {PAGE_SEPARATION, PAGE_CONVERSION, PAGE_STUDIO}
        if previous_index != index and not ({previous_index, index} <= workspace_pages):
            self._suspend_playback()
        if index != PAGE_MODELS:
            self.model_workspace_page.stop_preview()
        # Populate the hidden Studio workspace before exposing it. Otherwise the
        # already-built video panel paints one frame ahead of the sound pool and timeline.
        if index == PAGE_STUDIO:
            self._restore_current_studio_session()
        self.page_stack.setCurrentIndex(index)
        self.primary_navigation.set_current_page(index)
        if index == PAGE_EXPORT:
            self._refresh_export_page()
        if index == PAGE_STUDIO:
            self._prepare_studio_playback_surface()
        elif previous_index in workspace_pages and index in workspace_pages:
            self._sync_playback_queue_for_page(index, force=True)
        else:
            self._sync_playback_queue_for_page(index)
        self._sync_playback_surfaces()
        self._sync_video_workspace()
        QTimer.singleShot(0, self._sync_playback_surfaces)

    def _navigate_to_vocal_step(self, index: int) -> None:
        self._navigate_to_page(PAGE_SEPARATION if index == 0 else PAGE_CONVERSION)

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
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_MEDIA_EXTENSIONS))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select Media"),
            str(Path.home()),
            f"{tr('Media Files')} ({suffixes})",
        )
        if not filename:
            return
        self._start_video_file_import(Path(filename))

    def _attach_video_files(self, paths: object) -> None:
        candidates = [
            Path(path)
            for path in paths
            if Path(path).suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS
        ] if isinstance(paths, (list, tuple)) else []
        if not candidates:
            self.video_preview_panel.set_status("Select a supported video or image file.")
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
        self.video_preview_panel.set_status("Importing media")
        worker = TaskWorker(lambda progress: self.library.set_video_file(scope.song_id, source, progress))
        self._run_worker(
            worker,
            lambda result: self._on_video_source_attached(scope, result),
            lambda error: self._on_video_source_failed(scope, error),
            self.video_preview_panel,
            task_title="Import Media",
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
        self.video_preview_panel.set_status("Media attached")
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
        self.video_preview_panel.set_status("Media source cleared")
        self._refresh_open_library_details(item.id)

    def _select_saved_video_source(self, path: Path) -> None:
        item = self.current_work_item
        if item is None:
            return
        try:
            source = self.library.select_managed_video(item.id, path)
        except (KeyError, ValueError) as exc:
            self.video_preview_panel.set_status(str(exc))
            return
        self._set_video_source(source, enabled=True)
        self.video_preview_panel.set_status("Saved media selected")
        self._refresh_open_library_details(item.id)

    def _on_video_source_attached(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_open_library_details(scope.song_id)
        if not scope.is_current(self.current_work_item) or not isinstance(result, VideoSource):
            return
        self._set_video_source(result, enabled=True)
        self.video_preview_panel.set_status("Media attached")

    def _on_video_downloaded(self, scope: WorkTaskScope, result: object) -> None:
        self._refresh_open_library_details(scope.song_id)
        if not scope.is_current(self.current_work_item) or not isinstance(result, VideoSource):
            return
        self._set_video_source(result, enabled=True)
        self.video_preview_panel.set_progress(100)
        self.video_preview_panel.set_status("Video downloaded")

    def _on_video_source_failed(self, scope: WorkTaskScope, error: str) -> None:
        if scope.is_current(self.current_work_item):
            self.video_preview_panel.set_status(f"Media failed: {_last_error_line(error)}", error)

    def _open_video_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            self.video_preview_panel.set_status(f"Open failed: {_last_error_line(str(exc))}")

    def _start_video_render(self, song_id: str, settings: VideoExportSettings) -> None:
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
        worker = TaskWorker(
            lambda progress: self.library.render_video(scope.song_id, settings, progress)
        )
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
        self.song_list.blockSignals(True)
        self.song_list.clear()
        items = self.library.items()
        self._song_items_by_id = {item.id: item for item in items}
        if self._library_preview_song_id not in self._song_items_by_id:
            if self._current_playback_context() == "library":
                self._stop_playback(clear_queue=True)
            self._library_preview_song_id = ""
        session = MainWindow._work_song_session(self)
        session.refresh(self._song_items_by_id)
        MainWindow._sync_work_song_session_state(self, session)
        sort_mode = str(self.library_sort_combo.currentData() or "newest")
        for item in sort_song_items(items, sort_mode):
            metadata = build_song_display_metadata(item, self.settings.output_root)
            row = SongListRow(
                item.id,
                item.title,
                metadata,
                self.song_list.viewport(),
            )
            row.set_theme_mode(self.settings.theme_mode)
            apply_widget_language(row)
            row.work_song_toggled.connect(self._toggle_library_work_song)
            row.details_requested.connect(self._open_library_details)
            row.rename_requested.connect(self._rename_library_item)
            row.remove_requested.connect(self._remove_library_item)
            row.preview_requested.connect(self._toggle_library_preview)
            row.preview_play_toggled.connect(self._toggle_library_preview_playback)
            row.preview_seek_requested.connect(self._seek_library_preview)
            row.preview_height_changed.connect(self._sync_library_row_height)
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            attach_list_item_widget(self.song_list, list_item, row)
            if item.id == self._library_preview_song_id:
                row.set_preview_expanded(True)
                list_item.setSizeHint(row.sizeHint())
        self.song_list.blockSignals(False)
        if selected_id and self._select_library_song(selected_id):
            pass
        elif self.song_list.count() > 0:
            self.song_list.setCurrentRow(0)
        self._sync_work_song_rows()
        self._sync_navigation_work_song_selector()
        self._apply_library_filters()
        self._sync_result_song_titles()
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

    def _toggle_library_preview(self, song_id: str) -> None:
        if song_id == self._library_preview_song_id:
            if self._current_playback_context() == "library":
                self._stop_playback(clear_queue=True)
            self._playback_resume_positions.pop(("library", song_id), None)
            self._set_library_preview_expanded(song_id, False)
            self._library_preview_song_id = ""
            return

        previous_id = self._library_preview_song_id
        if previous_id:
            self._set_library_preview_expanded(previous_id, False)
        if self._current_playback_context() == "library":
            self._suspend_playback()

        song = self._song_items_by_id.get(song_id)
        if song is None:
            self._library_preview_song_id = ""
            return
        self._select_library_song(song_id)
        self._library_preview_song_id = song_id
        self._set_library_preview_expanded(song_id, True)
        self._load_library_playback_queue(song)

    def _toggle_library_preview_playback(self, song_id: str) -> None:
        if song_id != self._library_preview_song_id:
            self._toggle_library_preview(song_id)
        queue = self.current_playback_queue
        if queue is None or queue.context != "library" or queue.source_id != song_id:
            song = self._song_items_by_id.get(song_id)
            if song is None:
                return
            self._load_library_playback_queue(song)
        self._toggle_global_playback()

    def _seek_library_preview(self, song_id: str, position_ms: int) -> None:
        queue = self.current_playback_queue
        if queue is None or queue.context != "library" or queue.source_id != song_id:
            return
        self._seek_global_playback(position_ms)

    def _set_library_preview_expanded(self, song_id: str, is_expanded: bool) -> None:
        list_item, row = self._library_row(song_id)
        if list_item is None or row is None:
            return
        row.set_preview_expanded(is_expanded)
        list_item.setSizeHint(row.sizeHint())

    def _sync_library_row_height(self, song_id: str) -> None:
        list_item, row = self._library_row(song_id)
        if list_item is not None and row is not None:
            list_item.setSizeHint(row.sizeHint())

    def _library_row(self, song_id: str) -> tuple[QListWidgetItem | None, SongListRow | None]:
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) != song_id:
                continue
            row = self.song_list.itemWidget(item)
            return item, row if isinstance(row, SongListRow) else None
        return None, None

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
        visible_items = []
        preview_is_visible = False
        for index in range(self.song_list.count()):
            list_item = self.song_list.item(index)
            song_id = list_item.data(Qt.ItemDataRole.UserRole)
            song = self._song_items_by_id.get(song_id)
            is_visible = song is not None and (
                not query or query in song.title.casefold() or query in song.path.name.casefold()
            )
            list_item.setHidden(not is_visible)
            if is_visible:
                visible_items.append(list_item)
            if song_id == self._library_preview_song_id:
                preview_is_visible = is_visible

        if self._library_preview_song_id and not preview_is_visible:
            preview_song_id = self._library_preview_song_id
            self._set_library_preview_expanded(preview_song_id, False)
            if self._current_playback_context() == "library":
                self._stop_playback(clear_queue=True)
            else:
                self._library_preview_song_id = ""

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
        opening_from_list = self.library_content_stack.currentWidget() is not self.library_details_panel
        if opening_from_list and self._current_playback_context() == "library":
            self._suspend_playback()
        self.library_details_panel.set_details(details)
        self.library_content_stack.setCurrentWidget(self.library_details_panel)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "library_asset":
            path = Path(queue.source_id)
            self.library_details_panel.set_preview_expanded(path, True)
            self._refresh_playback_ui(is_playing=self.player.is_playing())

    def _close_library_details(self) -> None:
        if self._current_playback_context() == "library_asset":
            self._suspend_playback()
        self.library_details_panel.clear_preview()
        self.library_content_stack.setCurrentIndex(0)

    def _toggle_library_asset_preview(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        source_id = str(resolved)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "library_asset" and queue.source_id == source_id:
            self._playback_resume_positions.pop(("library_asset", source_id), None)
            self._stop_playback(clear_queue=True)
            return

        if queue is not None and queue.context in {"library", "library_asset"}:
            self._suspend_playback()
        preview_queue = self._library_asset_playback_queue(resolved)
        if preview_queue is None:
            return
        self.library_details_panel.set_preview_expanded(resolved, True)
        self._set_playback_queue(
            preview_queue,
            position_ms=self._resume_position(preview_queue),
        )

    def _toggle_library_asset_preview_playback(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        source_id = str(resolved)
        queue = self.current_playback_queue
        if queue is None or queue.context != "library_asset" or queue.source_id != source_id:
            self._toggle_library_asset_preview(resolved)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "library_asset" and queue.source_id == source_id:
            self._toggle_global_playback()

    def _seek_library_asset_preview(self, path: Path, position_ms: int) -> None:
        queue = self.current_playback_queue
        if (
            queue is None
            or queue.context != "library_asset"
            or queue.source_id != str(path.expanduser().resolve())
        ):
            return
        self._seek_global_playback(position_ms)

    def _toggle_export_preview(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        source_id = str(resolved)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "export" and queue.source_id == source_id:
            self._playback_resume_positions.pop(("export", source_id), None)
            self._stop_playback(clear_queue=True)
            return

        if queue is not None:
            self._suspend_playback()
        preview_queue = self._export_playback_queue(resolved)
        if preview_queue is None:
            return
        self.export_page.set_preview_expanded(resolved, True)
        self._set_playback_queue(
            preview_queue,
            position_ms=self._resume_position(preview_queue),
        )

    def _toggle_export_preview_playback(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        source_id = str(resolved)
        queue = self.current_playback_queue
        if queue is None or queue.context != "export" or queue.source_id != source_id:
            self._toggle_export_preview(resolved)
        queue = self.current_playback_queue
        if queue is not None and queue.context == "export" and queue.source_id == source_id:
            self._toggle_global_playback()

    def _seek_export_preview(self, path: Path, position_ms: int) -> None:
        queue = self.current_playback_queue
        if (
            queue is None
            or queue.context != "export"
            or queue.source_id != str(path.expanduser().resolve())
        ):
            return
        self._seek_global_playback(position_ms)

    def _open_library_asset_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            _set_optional_label(self.library_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _remove_library_asset(self, song_id: str, asset: SongAsset) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None or not asset.can_remove:
            return

        if asset.removal_scope == REMOVAL_VOCAL_OUTPUT:
            message = (
                tr("Remove this linked vocal result from the song? The external files will not be deleted.")
                if not asset.is_managed
                else tr(
                    "Delete this separation result and all converted vocals inside it? "
                    "This cannot be undone."
                )
            )
        elif asset.removal_scope == REMOVAL_STUDIO_SESSION:
            message = tr(
                "Reset the studio session for this song? Timeline edits and mix settings will be removed."
            )
        else:
            message = tr(
                "Delete '{name}' from this song? This cannot be undone.",
                name=asset.path.name,
            )
        if not ConfirmationDialog.confirm(
            self,
            tr("Remove Library Data"),
            message,
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Remove"),
            cancel_label=tr("Cancel"),
        ):
            return

        self._execute_library_asset_removal(song_id, (asset,))

    def _remove_studio_pool_asset(self, asset: StudioSoundAsset) -> None:
        song = self.current_song or self.current_work_item
        if song is None:
            return
        try:
            details = self.library.asset_details(song.id)
        except KeyError:
            return
        target = next(
            (
                candidate
                for candidate in details.assets
                if candidate.can_remove and _same_path(candidate.path, asset.path)
            ),
            None,
        )
        if target is None:
            self.studio_editor.set_status(
                tr("This file can only be removed by deleting the entire song.")
            )
            return
        self._remove_library_asset(song.id, target)

    def _remove_library_assets(self, song_id: str, assets: tuple[SongAsset, ...]) -> None:
        removable = tuple(asset for asset in assets if asset.can_remove)
        if not removable or song_id not in self._song_items_by_id:
            return
        message = tr(
            "Delete {count} selected items? Vocal result files may remove their entire "
            "separation result. This cannot be undone.",
            count=len(removable),
        )
        if not ConfirmationDialog.confirm(
            self,
            tr("Delete Selected Files"),
            message,
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Delete"),
            cancel_label=tr("Cancel"),
        ):
            return
        self._execute_library_asset_removal(song_id, removable)

    def _execute_library_asset_removal(
        self,
        song_id: str,
        assets: tuple[SongAsset, ...],
    ) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None or not assets:
            return

        queue = self.current_playback_queue
        affects_playback = queue is not None and any(
            any(_same_path(path, asset.path) for path in queue.paths)
            or (
                asset.removal_scope == REMOVAL_VOCAL_OUTPUT
                and any(_is_path_within(path, asset.path.parent) for path in queue.paths)
            )
            for asset in assets
        )
        if affects_playback:
            self._stop_playback(clear_queue=True)

        try:
            results = self.library.remove_assets(
                song_id,
                tuple(asset.path for asset in assets),
            )
        except Exception as exc:
            _set_optional_label(self.library_status_label, f"Remove failed: {_last_error_line(str(exc))}")
            self._refresh_song_list()
            return

        if any(asset.removal_scope == REMOVAL_STUDIO_SESSION for asset in assets):
            self.studio_session_autosave.discard(song_id)

        preferred_output = None
        if self.current_work_item is not None and self.current_work_item.id == song_id:
            try:
                refreshed_song = next(item for item in self.library.items() if item.id == song_id)
            except StopIteration:
                refreshed_song = None
            self._assign_work_item(refreshed_song, persist=False)
            preferred_output = refreshed_song.output_job_dir if refreshed_song is not None else None

        has_vocal_removal = any(
            asset.removal_scope in {REMOVAL_VOCAL_OUTPUT, REMOVAL_VOCAL_TAKE}
            for asset in assets
        )
        if has_vocal_removal:
            self._refresh_output_sets(
                preferred_job_dir=preferred_output,
                select_fallback=preferred_output is not None,
            )
        else:
            self._refresh_song_list()
        if self.current_work_item is not None and self.current_work_item.id == song_id:
            if any(asset.stage == STAGE_STUDIO for asset in assets):
                self._restore_current_studio_session()
            self._refresh_video_source()
            self._refresh_output_playback_queue()
        _set_optional_label(
            self.library_status_label,
            "Link removed"
            if results and all(result.detached_only for result in results)
            else "Removed",
        )

    def _sync_work_song_rows(self) -> None:
        work_song_id = MainWindow._work_song_session(self).selected_id
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            row = self.song_list.itemWidget(item)
            if hasattr(row, "set_work_song_active"):
                row.set_work_song_active(
                    item.data(Qt.ItemDataRole.UserRole) == work_song_id
                )

    def _sync_navigation_work_song_selector(self) -> None:
        if not hasattr(self, "primary_navigation"):
            return
        selected_id = MainWindow._work_song_session(self).selected_id
        songs = sort_song_items(list(self._song_items_by_id.values()), "newest")
        self.primary_navigation.set_work_songs(
            ((song.id, song.title) for song in songs),
            selected_id,
        )

    def _on_navigation_work_song_changed(self, song_id: str) -> None:
        session = MainWindow._work_song_session(self)
        route = session.navigation_route(
            song_id,
            self._song_items_by_id,
            load_in_progress=MainWindow._work_song_change_in_progress(self),
        )
        if route.action == "sync_selector":
            self._sync_navigation_work_song_selector()
            return
        if route.action == "clear":
            self._set_current_song(None)
            return
        if route.song is None:
            return
        if route.action == "load_output":
            self._start_library_work_song_load(route.song)
            return
        self._select_work_song(route.song)

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

        session = MainWindow._playback_session(self)
        if session.replace_title("library", song_id, new_title) is not None:
            MainWindow._sync_playback_session_state(self, session)
        _set_optional_label(self.library_status_label, "Renamed")
        self._refresh_song_list()
        self._select_library_song(song_id)
        if self.current_work_item is not None and self.current_work_item.id == song_id:
            self._assign_work_item(self._song_items_by_id.get(song_id), persist=False)

    def _remove_library_item(self, song_id: str) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            return

        if not ConfirmationDialog.confirm(
            self,
            tr("Delete Song"),
            tr(
                "Delete '{name}' and all files managed by JJZero Audio for this song? "
                "Original or linked files outside the library will not be deleted. "
                "This cannot be undone.",
                name=song.title,
            ),
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Delete"),
            cancel_label=tr("Cancel"),
        ):
            return

        was_current_song = self.current_song is not None and self.current_song.id == song_id
        was_work_item = self.current_work_item is not None and self.current_work_item.id == song_id
        queue = self.current_playback_queue
        package_dir = song.package_dir
        affects_playback = queue is not None and (
            queue.source_id == song_id
            or was_current_song
            or was_work_item
            or (
                package_dir is not None
                and any(_is_path_within(path, package_dir) for path in queue.paths)
            )
        )
        if affects_playback:
            self._stop_playback(clear_queue=True)
            self._library_preview_song_id = ""
        self._playback_resume_positions.pop(("library", song_id), None)
        self.studio_session_autosave.discard(song_id)
        try:
            removed = self.library.remove_item(song_id)
        except Exception as exc:
            _set_optional_label(
                self.library_status_label,
                f"Delete failed: {_last_error_line(str(exc))}",
            )
            return
        if not removed:
            return

        if was_current_song or was_work_item:
            self._set_current_song(None)
        _set_optional_label(self.library_status_label, tr("Deleted"))
        self._refresh_song_list()

    def _sync_result_song_titles(self) -> None:
        title = MainWindow._work_song_session(self).title
        if hasattr(self, "separation_results_panel"):
            self.separation_results_panel.set_song_title(title)
        if hasattr(self, "vocal_results_panel"):
            self.vocal_results_panel.set_song_title(title)

    def _set_current_song(self, song: SongItem | None, *, persist: bool = True) -> None:
        session = MainWindow._work_output_session(self)
        sound_set = (
            session.load_sound_set(song.output_job_dir, self.settings.output_root)
            if song is not None and song.output_job_dir is not None
            else None
        )
        self._apply_loaded_work_song(song, sound_set, persist=persist)

    def _set_output_work_song(self, song: SongItem, *, persist: bool = True) -> bool:
        session = MainWindow._work_output_session(self)
        sound_set = (
            session.load_sound_set(song.output_job_dir, self.settings.output_root)
            if song.output_job_dir is not None
            else None
        )
        return self._apply_loaded_work_song(song, sound_set, persist=persist)

    def _apply_loaded_work_song(
        self,
        song: SongItem | None,
        sound_set: OutputSoundSet | None,
        *,
        persist: bool = True,
    ) -> bool:
        self._assign_work_item(song, persist=persist)
        if song is None or song.output_job_dir is None or sound_set is None:
            self._apply_output_set(None)
            return False
        self._select_output_set(sound_set.job_dir)
        self._apply_output_set(sound_set)
        return True

    def _assign_work_item(self, item: SongItem | None, *, persist: bool = True) -> None:
        for step in self._assign_work_item_steps(item, persist=persist):
            step()

    def _assign_work_item_steps(
        self,
        item: SongItem | None,
        *,
        persist: bool = True,
    ) -> tuple[Callable[[], None], ...]:
        session = MainWindow._work_song_session(self)

        def assign_session() -> None:
            try:
                session.assign(item, persist=persist)
            except OSError as exc:
                _set_optional_label(
                    self.output_status_label,
                    f"Work song failed: {_last_error_line(str(exc))}",
                )
            MainWindow._sync_work_song_session_state(self, session)

        def reset_result_state() -> None:
            self.separation_action.set_progress(0)
            self.separation_action.set_status("")
            self._sync_result_song_titles()

        def sync_library_row() -> None:
            if hasattr(self, "song_list"):
                self._sync_work_song_rows()

        return (
            assign_session,
            reset_result_state,
            sync_library_row,
            self._sync_work_song_navigation,
            self._sync_work_song_capabilities,
            self._refresh_video_source,
        )

    def _sync_work_song_navigation(self) -> None:
        if not hasattr(self, "primary_navigation"):
            return
        sync_selector = getattr(self, "_sync_navigation_work_song_selector", None)
        if callable(sync_selector):
            sync_selector()
        has_work_song = MainWindow._work_song_session(self).has_selection()
        locked_tooltip = tr("Select a work song in Library to unlock this page.")
        for page_id in WORK_SONG_REQUIRED_PAGES:
            self.primary_navigation.set_page_enabled(
                page_id,
                has_work_song,
                disabled_tooltip=locked_tooltip,
            )
        self.primary_navigation.set_page_enabled(PAGE_EXPORT, True)
        if (
            not has_work_song
            and hasattr(self, "page_stack")
            and self.page_stack.currentIndex() in WORK_SONG_REQUIRED_PAGES
        ):
            self._navigate_to_page(PAGE_LIBRARY)

    def _sync_work_song_capabilities(self) -> None:
        capabilities = MainWindow._work_song_session(self).capabilities(
            output_available=self._current_output_matches_work_song(),
        )
        self.separation_action.set_button_text(
            "Link Original" if capabilities.can_attach_source else "Separate"
        )
        self.separation_action.set_action_enabled(
            capabilities.can_separate or capabilities.can_attach_source
        )
        if capabilities.can_attach_source:
            self.separation_action.set_status("Link the original audio to separate it again.")
        self.rvc_action.set_action_enabled(capabilities.can_convert)

    def _current_output_matches_work_song(self) -> bool:
        return MainWindow._work_output_session(self).matches_work_item(
            self.current_work_item
        )

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
        saved_sources = ()
        if item is not None:
            try:
                saved_sources = self.library.managed_video_sources(item.id)
            except KeyError:
                pass
        self.video_preview_panel.set_source(
            source,
            enabled=enabled,
            original_song_url=original_url,
            saved_sources=saved_sources,
        )
        if (
            hasattr(self, "studio_editor")
            and item is not None
            and self.page_stack.currentIndex() == PAGE_STUDIO
            and not getattr(self, "_is_loading_studio_session", False)
        ):
            self._restore_current_studio_session()
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
        if video_active and self.studio_editor.has_media_track():
            media = self.studio_editor.media_at(self._playback_position_ms)
            if media is None:
                self.video_preview_panel.sync_timeline_media(None, "", 0, False)
            else:
                asset, source_position_ms, media_settings = media
                self.video_preview_panel.sync_timeline_media(
                    asset.path,
                    asset.media_kind,
                    source_position_ms,
                    is_playing and self._current_playback_context() == "output",
                    media_settings,
                )
            return
        self.video_preview_panel.sync_playback(
            self._playback_position_ms,
            video_active and is_playing and self._current_playback_context() == "output",
        )

    def _restore_work_song(self) -> None:
        session = MainWindow._work_song_session(self)
        route = session.restore_route(self._song_items_by_id)
        MainWindow._sync_work_song_session_state(self, session)
        if route.action == "load_output" and route.song is not None:
            self._set_output_work_song(route.song, persist=False)
        elif route.action == "select" and route.song is not None:
            self._set_current_song(route.song, persist=False)
        else:
            self._set_current_song(None, persist=False)

    def _select_work_song(self, song: SongItem) -> None:
        if song.kind == "output":
            self._set_output_work_song(song)
        else:
            self._set_current_song(song)

    def _toggle_library_work_song(self, song_id: str) -> None:
        route = MainWindow._work_song_session(self).toggle_route(
            song_id,
            self._song_items_by_id,
            load_in_progress=MainWindow._work_song_change_in_progress(self),
        )
        if route.action == "ignore":
            return
        if route.action == "clear":
            self._set_current_song(None)
            return
        if route.song is None:
            return
        if route.action == "load_output":
            self._start_library_work_song_load(route.song)
            return
        self._select_work_song(route.song)

    def _start_library_work_song_load(self, song: SongItem) -> None:
        if song.output_job_dir is None:
            self._select_work_song(song)
            return
        cached = MainWindow._work_output_session(self).sound_set_for_job(song.output_job_dir)
        if cached is not None:
            self._apply_loaded_work_song(song, cached)
            return
        self._work_song_loading_id = song.id
        self._set_library_work_song_loading(song.id, True)
        worker = TaskWorker(
            lambda _progress: load_output_sound_set(
                song.output_job_dir,
                self.settings.output_root,
            )
        )
        self._work_song_load_worker = worker
        self._workers.append(worker)

        def complete(result: object) -> None:
            current = self._song_items_by_id.get(song.id)
            if current is None:
                self._finish_library_work_song_load(song.id)
                return
            self._apply_loaded_work_song_deferred(
                current,
                result if isinstance(result, OutputSoundSet) else None,
                completed=lambda: self._finish_library_work_song_load(song.id),
            )

        def failed(error: str) -> None:
            self._logger.warning("Work-song load failed: %s", _last_error_line(error))
            _set_optional_label(
                self.library_status_label,
                f"Load failed: {_last_error_line(error)}",
            )
            self._finish_library_work_song_load(song.id)
            self._sync_navigation_work_song_selector()

        def cleanup() -> None:
            if self._work_song_load_worker is worker:
                self._work_song_load_worker = None
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        worker.succeeded.connect(complete)
        worker.failed.connect(failed)
        worker.finished.connect(cleanup)
        worker.start()

    def _work_song_change_in_progress(self) -> bool:
        return bool(
            getattr(self, "_work_song_load_worker", None) is not None
            or getattr(self, "_work_song_loading_id", "")
        )

    def _apply_loaded_work_song_deferred(
        self,
        song: SongItem,
        sound_set: OutputSoundSet | None,
        *,
        completed: Callable[[], None],
    ) -> None:
        def apply_output() -> None:
            if song.output_job_dir is None or sound_set is None:
                self._apply_output_set(None, deferred=True, completed=completed)
                return
            self._select_output_set(sound_set.job_dir)
            self._apply_output_set(sound_set, deferred=True, completed=completed)

        self._run_ui_steps(
            self._assign_work_item_steps(song),
            completed=apply_output,
        )

    def _finish_library_work_song_load(self, song_id: str) -> None:
        self._set_library_work_song_loading(song_id, False)
        if self._work_song_loading_id == song_id:
            self._work_song_loading_id = ""

    def _set_library_work_song_loading(self, song_id: str, is_loading: bool) -> None:
        navigation = getattr(self, "primary_navigation", None)
        selector = getattr(navigation, "work_song_selector", None)
        if (
            selector is not None
            and selector.selected_song_id() == song_id
            and hasattr(selector, "set_loading")
        ):
            selector.set_loading(is_loading)
        for index in range(self.song_list.count()):
            item = self.song_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) != song_id:
                continue
            row = self.song_list.itemWidget(item)
            if hasattr(row, "set_work_song_loading"):
                row.set_work_song_loading(is_loading)
            return

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

    def _library_asset_playback_queue(self, path: Path) -> PlaybackQueue | None:
        return MainWindow._single_file_playback_queue(self, path, context="library_asset")

    def _export_playback_queue(self, path: Path) -> PlaybackQueue | None:
        return MainWindow._single_file_playback_queue(self, path, context="export")

    def _single_file_playback_queue(
        self,
        path: Path,
        *,
        context: str,
    ) -> PlaybackQueue | None:
        resolved = path.expanduser().resolve()
        if resolved.suffix.casefold() not in SUPPORTED_AUDIO_EXTENSIONS or not resolved.is_file():
            self._set_file_preview_error(context, "Cannot preview.")
            return None
        try:
            duration_ms = self._duration_ms_for_paths([resolved])
        except Exception as exc:
            self._set_file_preview_error(
                context,
                f"Load failed: {_last_error_line(str(exc))}",
            )
            return None
        if duration_ms <= 0:
            self._set_file_preview_error(context, "Cannot preview.")
            return None
        return PlaybackQueue(
            context=context,
            source_id=str(resolved),
            title=resolved.name,
            paths=(resolved,),
            volumes=(1.0,),
            duration_ms=duration_ms,
        )

    def _set_file_preview_error(self, context: str, message: str) -> None:
        if context == "export":
            self.export_page.set_audio_status(message)
        else:
            _set_optional_label(self.library_status_label, message)

    def _song_playback_paths(self, song: SongItem) -> list[Path]:
        if song.kind != "output":
            return [song.path]
        if song.output_job_dir is None:
            raise AudioPlaybackError("Output item has no job folder.")

        sound_set = MainWindow._work_output_session(self).load_sound_set(
            song.output_job_dir,
            self.settings.output_root,
        )
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

    def _selected_separation_recipe(self) -> SeparationRecipe:
        return self.separation_recipe_selector.selected_recipe()

    def _start_separation(self, *_args) -> None:
        song = self.current_work_item
        if song is not None and (song.kind != "source" or not song.path.is_file()):
            self._attach_separation_source(song)
            return
        if song is None:
            self.separation_action.set_status("Select song.")
            return

        self._stop_playback()
        self.separation_action.set_running(True)
        self.separation_action.set_progress(3)
        recipe = self._selected_separation_recipe()
        asset_status = separation_recipe_asset_status(recipe)
        self.separation_action.set_status(
            "Separating" if asset_status.ready else "Preparing separation model"
        )
        scope = WorkTaskScope(song.id)
        output_root = self.library.create_vocal_separation_run(song.id)
        worker = TaskWorker(
            lambda progress: separate_audio(
                song.path,
                output_root=output_root,
                progress_callback=progress,
                recipe=recipe,
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

    def _attach_separation_source(self, song: SongItem) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_AUDIO_EXTENSIONS))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select Original Audio"),
            str(Path.home()),
            f"{tr('Audio Files')} ({suffixes})",
        )
        if not filename:
            return
        try:
            restored = self.library.attach_source(song.id, Path(filename))
        except (KeyError, OSError, ValueError) as exc:
            self.separation_action.set_status("Could not link the original audio.")
            self.separation_action.status_label.setToolTip(_last_error_line(str(exc)))
            return

        self._song_items_by_id[restored.id] = restored
        self._set_current_song(restored)
        self._refresh_song_list()
        self.separation_action.set_status("Original audio linked. Ready to separate.")

    def _on_separation_succeeded(self, scope: WorkTaskScope, result: object) -> None:
        self.separation_recipe_selector.refresh_asset_status()
        separation_result = result if isinstance(result, SeparationResult) else None
        if separation_result is None:
            if scope.is_current(self.current_work_item):
                self.separation_action.set_status("Failed")
            return

        self.library.register_output(
            scope.song_id,
            separation_result.job_dir,
            separation_result.recipe.label,
        )
        self._refresh_output_sets_after_task(scope, separation_result.job_dir)
        if scope.is_current(self.current_work_item):
            self.separation_action.set_progress(100)
            self.separation_action.set_status("Done")

    def _on_separation_failed(self, scope: WorkTaskScope, error: str) -> None:
        self.separation_recipe_selector.refresh_asset_status()
        if not scope.is_current(self.current_work_item):
            return
        self.separation_action.set_status("Failed")
        self.separation_action.status_label.setToolTip(f"{LOG_FILE}\n{_last_error_line(error)}")

    def _refresh_output_sets_after_task(self, scope: WorkTaskScope, completed_job_dir: Path) -> None:
        target = MainWindow._work_output_session(self).refresh_target(
            scope.song_id,
            completed_job_dir,
            self.current_work_item,
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
        session = MainWindow._work_output_session(self)
        legacy_sound_sets = scan_output_sound_sets(self.settings.output_root)
        self.library.add_output_sets(legacy_sound_sets)
        sound_sets = self.library.output_sound_sets()
        if hasattr(self, "song_list"):
            self._refresh_song_list()

        self.output_set_combo.blockSignals(True)
        self.output_set_combo.clear()
        for sound_set in sound_sets:
            self.output_set_combo.addItem(sound_set.label, str(sound_set.job_dir))

        selection = session.refresh_catalog(
            sound_sets,
            preferred_job_dir=preferred_job_dir,
            select_fallback=select_fallback,
        )
        MainWindow._sync_work_output_session_state(self, session)

        if not sound_sets:
            self.output_set_combo.blockSignals(False)
            self._apply_output_set(None)
            return

        if selection.selected_index < 0 or selection.sound_set is None:
            self.output_set_combo.setCurrentIndex(-1)
            self.output_set_combo.blockSignals(False)
            self._apply_output_set(None)
            return

        self.output_set_combo.setCurrentIndex(selection.selected_index)
        self.output_set_combo.blockSignals(False)
        self._apply_output_set(selection.sound_set)

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
        index = MainWindow._work_output_session(self).selected_index_for_job(job_dir)
        if index < 0:
            return
        was_blocked = self.output_set_combo.blockSignals(True)
        self.output_set_combo.setCurrentIndex(index)
        self.output_set_combo.blockSignals(was_blocked)

    def _on_output_set_changed(self, *_args) -> None:
        data = self.output_set_combo.currentData()
        if not data:
            self._apply_output_set(None)
            return
        self._activate_output_job(Path(data))

    def _activate_output_job(self, job_dir: Path) -> None:
        session = MainWindow._work_output_session(self)
        song = self.library.activate_output(job_dir)
        if song is not None:
            self._song_items_by_id[song.id] = song
            self._assign_work_item(song)
        sound_set = session.load_sound_set(job_dir, self.settings.output_root)
        self._apply_output_set(sound_set)

    def _activate_vocal_converted_version(self, path: Path | None) -> None:
        if path is None:
            return
        convert_session = MainWindow._work_convert_session(self)
        owner = (
            convert_session.version_for_converted_path(path)
            or self.conversion_result_browser.version_for_path(path)
        )
        job_dir = (
            owner.job_dir
            if owner is not None
            else convert_session.job_dir_for_converted_path(
                path,
                fallback_job_dir=MainWindow._work_output_session(self).job_dir,
            )
        )
        if job_dir is None:
            return
        convert_session.remember_converted_owner(owner, path)
        try:
            project = self.vocal_project_store.set_active_take(job_dir, path)
            convert_session.remember_project(job_dir, project)
        except Exception as exc:
            self._logger.warning("Could not persist active vocal take: %s", exc)
        song = self.library.activate_converted_output(job_dir, path)
        if song is not None:
            self._song_items_by_id[song.id] = song
        self.converted_track.select_path(path)
        self.conversion_result_browser.select_converted(path)
        MainWindow._sync_conversion_context_from_session(self)

    def _activate_separation_result(self, job_dir: Path) -> None:
        session = MainWindow._work_output_session(self)
        song = self.library.activate_output(job_dir)
        if song is None:
            return
        self._song_items_by_id[song.id] = song
        if self.current_work_item is not None and self.current_work_item.id == song.id:
            self._assign_work_item(song, persist=False)
        sound_set = session.load_sound_set(job_dir, self.settings.output_root)
        if sound_set is not None:
            self._apply_output_set(sound_set)

    def _open_vocal_output_location(self, job_dir: Path) -> None:
        try:
            open_in_file_browser(job_dir)
        except Exception as exc:
            _set_optional_label(self.output_status_label, f"Open failed: {_last_error_line(str(exc))}")

    def _open_vocal_take_location(self, path: Path) -> None:
        try:
            open_in_file_browser(path)
        except Exception as exc:
            self.rvc_action.set_status(f"Open failed: {_last_error_line(str(exc))}")

    def _rename_vocal_take(self, path: Path) -> None:
        take = self.vocal_results_panel.current_take()
        if take is None or take.output_path.expanduser().resolve() != path.expanduser().resolve():
            return
        job_dir = MainWindow._work_convert_session(self).job_dir_for_converted_path(
            path,
            fallback_job_dir=MainWindow._work_output_session(self).job_dir,
        )
        if job_dir is None:
            return
        label, accepted = TextInputDialog.get_text(
            self,
            tr("Rename Vocal Result"),
            tr("Result name"),
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Rename"),
            cancel_label=tr("Cancel"),
            initial_value=take.label,
        )
        if not accepted or label == take.label:
            return
        try:
            project = self.vocal_project_store.rename_take(job_dir, path, label)
            MainWindow._work_convert_session(self).remember_project(job_dir, project)
            self._refresh_vocal_project_panel()
        except Exception as exc:
            self.rvc_action.set_status(f"Rename failed: {_last_error_line(str(exc))}")

    def _remove_vocal_take(self, path: Path) -> None:
        take = self.vocal_results_panel.current_take()
        label = take.label if take is not None else path.stem
        job_dir = MainWindow._work_convert_session(self).job_dir_for_converted_path(
            path,
            fallback_job_dir=MainWindow._work_output_session(self).job_dir,
        )
        if job_dir is None:
            return
        confirmed = ConfirmationDialog.confirm(
            self,
            tr("Remove Vocal Result"),
            tr("Delete '{name}' from this vocal project? This cannot be undone.", name=label),
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Remove"),
            cancel_label=tr("Cancel"),
        )
        if not confirmed:
            return
        try:
            project = self.vocal_project_store.remove_take(job_dir, path)
            MainWindow._work_convert_session(self).remember_project(job_dir, project)
            active = _active_vocal_take_path(project)
            song = self.library.activate_converted_output(job_dir, active)
            if song is not None:
                self._song_items_by_id[song.id] = song
            refreshed = MainWindow._work_output_session(self).load_sound_set(
                job_dir,
                self.settings.output_root,
                reload=True,
            )
            self._apply_output_set(refreshed)
        except Exception as exc:
            self.rvc_action.set_status(f"Remove failed: {_last_error_line(str(exc))}")

    def _reconvert_vocal_take(self, path: Path) -> None:
        take = self.vocal_results_panel.current_take()
        if take is None or take.conversion is None:
            self.rvc_action.set_status("Conversion settings unavailable.")
            return
        conversion = take.conversion
        rvc_settings = replace(
            self.settings.rvc,
            model_id="",
            voice_model=conversion.voice_model,
            index_file=conversion.index_file,
            pitch=conversion.pitch,
            device=conversion.requested_device,
            f0_method=conversion.f0_method,
            inference=conversion.inference,
        )
        self.settings = replace(self.settings, rvc=rvc_settings)
        save_app_settings(self.settings)
        self._refresh_rvc_choices()
        self.pitch_spin.setValue(rvc_settings.pitch)
        self.device_combo.setCurrentText(normalize_rvc_device(rvc_settings.device))
        self.rvc_inference_controls.set_settings(rvc_settings.inference, emit=False)
        self._navigate_to_page(PAGE_CONVERSION)
        self._start_rvc_conversion()

    def _apply_output_set(
        self,
        sound_set: OutputSoundSet | None,
        *,
        deferred: bool = False,
        completed: Callable[[], None] | None = None,
    ) -> None:
        state: dict[str, object] = {}

        def assign_session() -> None:
            self.studio_session_autosave.flush()
            session = MainWindow._work_output_session(self)
            session.assign(sound_set)
            MainWindow._sync_work_output_session_state(self, session)
            linked_item = session.linked_output_item(
                self._song_items_by_id,
                current_source_item=self.current_song,
            )
            if linked_item is not None and linked_item != self.current_work_item:
                self._assign_work_item(linked_item)

        def clear_tracks() -> None:
            self.vocal_track.set_single_path(None)
            self.instrumental_track.set_single_path(None)
            self.converted_track.set_options([])
            if self.page_stack.currentIndex() == PAGE_STUDIO:
                self._apply_studio_session(StudioSession())

        def clear_result_pools() -> None:
            self.separation_stem_pool.set_versions((), None)
            self._apply_separation_stem_selection(None, None)
            versions = self._current_vocal_versions()
            self._refresh_conversion_input_choices(versions, None)

        def set_tracks() -> None:
            if sound_set is None:
                return
            self.vocal_track.set_single_path(sound_set.vocals_path)
            self.instrumental_track.set_single_path(sound_set.instrumental_path)
            selected_version = self._current_vocal_result(sound_set)
            state["selected_version"] = selected_version
            selected_converted = (
                selected_version.active_converted_path
                if isinstance(selected_version, SongVocalVersion)
                else None
            )
            self.converted_track.set_options(
                list(sound_set.converted_vocal_paths),
                selected_converted,
            )
            if self.page_stack.currentIndex() == PAGE_STUDIO:
                self._restore_current_studio_session()

        def refresh_separation_pool() -> None:
            selected_version = state.get("selected_version")
            self._refresh_separation_versions(
                selected_version if isinstance(selected_version, SongVocalVersion) else None
            )

        def refresh_conversion_pool() -> None:
            selected_version = state.get("selected_version")
            versions = self._current_vocal_versions()
            selected_job_dir = (
                selected_version.job_dir
                if isinstance(selected_version, SongVocalVersion)
                else None
            )
            self._refresh_conversion_input_choices(versions, selected_job_dir)

        def finalize_output() -> None:
            self.rvc_action.set_status("")
            _set_optional_label(self.output_status_label, "")
            self._refresh_output_playback_queue()
            self._sync_work_song_capabilities()
            self._refresh_export_page()

        steps: tuple[Callable[[], None], ...]
        if sound_set is None:
            steps = (assign_session, clear_tracks, clear_result_pools, finalize_output)
        else:
            steps = (
                assign_session,
                set_tracks,
                refresh_separation_pool,
                refresh_conversion_pool,
                lambda: self.rvc_action.set_progress(0),
                finalize_output,
            )
        if deferred:
            self._run_ui_steps(steps, completed=completed)
            return
        for step in steps:
            step()
        if completed is not None:
            completed()

    def _run_ui_steps(
        self,
        steps: tuple[Callable[[], None], ...],
        *,
        completed: Callable[[], None] | None = None,
    ) -> None:
        def run(index: int) -> None:
            if index >= len(steps):
                if completed is not None:
                    completed()
                return
            try:
                steps[index]()
            except Exception:
                self._logger.exception("Deferred UI update failed at step %s", index)
                if completed is not None:
                    completed()
                return
            QTimer.singleShot(1, lambda: run(index + 1))

        QTimer.singleShot(0, lambda: run(0))

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

    def _refresh_vocal_project_panel(self) -> None:
        if self.current_output_set is None:
            self.separation_stem_pool.set_versions((), None)
            self._apply_separation_stem_selection(None, None)
            self._refresh_conversion_input_choices(self._current_vocal_versions(), None)
            return
        result = self._current_vocal_result(self.current_output_set)
        self._refresh_separation_versions(result)
        self._refresh_conversion_input_choices(
            self._current_vocal_versions(),
            result.job_dir if result is not None else None,
        )

    def _refresh_separation_versions(self, selected: SongVocalVersion | None) -> None:
        versions = self._current_vocal_versions()
        vocal_result, instrumental_result = self.separation_stem_pool.set_versions(
            versions,
            selected.job_dir if selected is not None else None,
        )
        self._apply_separation_stem_selection(vocal_result, instrumental_result)

    def _on_separation_stem_selection_changed(
        self,
        vocal_result: SongVocalVersion | None,
        instrumental_result: SongVocalVersion | None,
    ) -> None:
        self._apply_separation_stem_selection(vocal_result, instrumental_result)
        self._refresh_output_playback_queue(WorkspacePlaybackScope.SEPARATION)

    def _apply_separation_stem_selection(
        self,
        vocal_result: SongVocalVersion | None,
        instrumental_result: SongVocalVersion | None,
    ) -> None:
        self._separation_preview_paths = {
            "original": vocal_result.vocals_path if vocal_result is not None else None,
            "instrumental": (
                instrumental_result.instrumental_path
                if instrumental_result is not None
                else None
            ),
        }
        self.separation_results_panel.set_separation_stems(
            vocal_result,
            instrumental_result,
        )

    def _current_vocal_versions(self) -> tuple[SongVocalVersion, ...]:
        item = self.current_song or self.current_work_item
        if item is None:
            return ()
        try:
            return self.library.vocal_versions(item.id)
        except KeyError:
            return ()

    def _refresh_conversion_input_choices(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
        preferred_converted_path: Path | None = None,
    ) -> None:
        convert_session = MainWindow._work_convert_session(self)
        context = convert_session.refresh(
            versions,
            current_output_job_dir=selected_job_dir,
            preferred_converted_path=preferred_converted_path,
        )
        self.conversion_input_pool.set_versions(
            versions,
            context.input_version.job_dir if context.input_version is not None else None,
            preserve_selection=False,
        )
        projects = convert_session.projects(
            self.vocal_project_store.load,
            on_error=self._on_conversion_project_load_failed,
        )
        self.conversion_result_browser.set_versions(
            versions,
            projects=projects,
            preferred_path=context.selected_converted_path,
        )
        convert_session.select_converted_path(
            self.conversion_result_browser.selected_path()
        )
        MainWindow._sync_conversion_context_from_session(self)

    def _on_conversion_input_version_changed(
        self,
        version: SongVocalVersion | None,
    ) -> None:
        MainWindow._work_convert_session(self).select_input_job_dir(
            version.job_dir if version is not None else None,
            clear_selected_converted=True,
        )
        self.conversion_result_browser.select_converted(None)
        MainWindow._sync_conversion_context_from_session(self)

    def _sync_conversion_context_from_session(self) -> None:
        context = MainWindow._work_convert_session(self).context()
        self._apply_conversion_result_context(
            context.result_version,
            selected_converted_path=context.selected_converted_path,
        )

    def _apply_conversion_result_context(
        self,
        version: SongVocalVersion | None,
        *,
        selected_converted_path: Path | None = None,
    ) -> None:
        projects = self.conversion_result_browser.projects()
        takes = tuple(take for project in projects for take in project.takes)
        selected_path = (
            selected_converted_path
            if selected_converted_path is not None
            else self.conversion_result_browser.selected_path()
        )
        self.vocal_results_panel.set_conversion_context(
            version,
            converted_paths=self.conversion_result_browser.converted_paths(),
            takes=takes,
            selected_converted_path=selected_path,
        )
        if self.page_stack.currentIndex() == PAGE_CONVERSION:
            self._refresh_output_playback_queue(WorkspacePlaybackScope.CONVERSION)

    def _on_conversion_project_load_failed(
        self,
        job_dir: Path,
        exc: Exception,
    ) -> None:
        self._logger.warning(
            "Could not load vocal project %s: %s",
            job_dir,
            exc,
        )

    def _choose_rvc_root(self, *_args) -> None:
        selected = QFileDialog.getExistingDirectory(self, tr("Select RVC Root"), self.rvc_root_edit.text())
        if not selected:
            return
        self.rvc_root_edit.setText(selected)
        self._save_rvc_settings_from_controls()
        self._refresh_rvc_choices()

    def _refresh_rvc_catalog(self, *_args) -> None:
        self.model_workspace_page.refresh_models()

    def _refresh_rvc_choices(self, *_args) -> None:
        self._is_loading_rvc_settings = True
        try:
            root = Path(
                self.rvc_root_edit.text().strip() or str(self.settings.rvc.root)
            )
            choices = collect_rvc_model_choices(
                self.model_workspace.records(),
                root,
                current_root=self.settings.rvc.root,
                current_model=self.settings.rvc.voice_model,
                execution_root=RVC_RUNTIME_DIR,
            )
            self._populate_model_combo(
                choices,
                self.settings.rvc.model_id,
                self.settings.rvc.root,
                self.settings.rvc.voice_model,
            )
            selected_model = self.model_combo.currentData()
            preferred_index = self.settings.rvc.index_file
            if (
                isinstance(selected_model, RvcModelChoice)
                and self.settings.rvc.model_id
                and selected_model.model_id == self.settings.rvc.model_id
            ):
                root = selected_model.root
                preferred_index = (
                    str(selected_model.index_path)
                    if selected_model.index_path is not None
                    and selected_model.index_path.is_file()
                    else ""
                )
                self.rvc_root_edit.setText(str(root))
            self._populate_combo(
                self.index_combo,
                list_index_files(root),
                preferred_index,
                "No index",
            )
        finally:
            self._is_loading_rvc_settings = False
        self._save_rvc_settings_from_controls()

    def _populate_model_combo(
        self,
        choices: tuple[RvcModelChoice, ...],
        current_model_id: str,
        current_root: Path,
        current_model: str,
    ) -> None:
        current_path = resolve_optional_rvc_setting_path(current_root, current_model)
        current_key = _resolved_path_key(current_path)
        label_counts: dict[str, int] = {}
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem(tr("Select model"), None)
        selected_model_index = 0
        selected_path_index = 0
        for choice in choices:
            folded_label = choice.label.casefold()
            label_counts[folded_label] = label_counts.get(folded_label, 0) + 1
            occurrence = label_counts[folded_label]
            label = choice.label if occurrence == 1 else f"{choice.label} ({occurrence})"
            self.model_combo.addItem(label, choice)
            index = self.model_combo.count() - 1
            self.model_combo.setItemData(
                index,
                str(choice.model_path),
                Qt.ItemDataRole.ToolTipRole,
            )
            if current_model_id and choice.model_id == current_model_id:
                selected_model_index = index
            if _resolved_path_key(choice.model_path) == current_key:
                selected_path_index = index
        self.model_combo.setCurrentIndex(
            selected_model_index or selected_path_index
        )
        self.model_combo.blockSignals(False)

    def _on_rvc_model_changed(self, *_args) -> None:
        if self._is_loading_rvc_settings:
            return
        choice = self.model_combo.currentData()
        if not isinstance(choice, RvcModelChoice):
            self._save_rvc_settings_from_controls()
            return
        self._apply_rvc_model_choice(choice)

    def _apply_rvc_model_choice(self, choice: RvcModelChoice) -> None:
        self._is_loading_rvc_settings = True
        try:
            self.rvc_root_edit.setText(str(choice.root))
            self.pitch_spin.setValue(choice.pitch)
            self.device_combo.setCurrentText(normalize_rvc_device(choice.device))
            preferred_index = (
                str(choice.index_path)
                if choice.index_path is not None and choice.index_path.is_file()
                else ""
            )
            self._populate_combo(
                self.index_combo,
                list_index_files(choice.root),
                preferred_index,
                "No index",
            )
        finally:
            self._is_loading_rvc_settings = False
        self.settings = replace(
            self.settings,
            rvc=RvcSettings(
                root=choice.root,
                model_id=choice.model_id,
                voice_model=str(choice.model_path),
                index_file=(
                    str(choice.index_path)
                    if choice.index_path is not None and choice.index_path.is_file()
                    else ""
                ),
                pitch=choice.pitch,
                device=normalize_rvc_device(choice.device),
                f0_method="rmvpe",
                inference=self.settings.rvc.inference,
            ),
        )
        save_app_settings(self.settings)

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
        selected_model = self.model_combo.currentData()
        voice_model = (
            str(selected_model.model_path)
            if isinstance(selected_model, RvcModelChoice)
            else ""
        )
        rvc_settings = RvcSettings(
            root=Path(self.rvc_root_edit.text().strip() or str(self.settings.rvc.root)),
            model_id=(
                selected_model.model_id
                if isinstance(selected_model, RvcModelChoice)
                else ""
            ),
            voice_model=voice_model,
            index_file=_combo_value(self.index_combo),
            pitch=self.pitch_spin.value(),
            device=self.device_combo.currentText(),
            f0_method="rmvpe",
            inference=(
                self.rvc_inference_controls.settings()
                if hasattr(self, "rvc_inference_controls")
                else self.settings.rvc.inference
            ),
        )
        self.settings = replace(self.settings, rvc=rvc_settings)
        save_app_settings(self.settings)

    def _on_rvc_inference_settings_changed(self, inference: RvcInferenceSettings) -> None:
        if self._is_loading_rvc_settings:
            return
        self.settings = replace(
            self.settings,
            rvc=replace(self.settings.rvc, inference=inference),
        )
        save_app_settings(self.settings)

    def _start_rvc_conversion(self, *_args) -> None:
        sound_set = self._conversion_input_sound_set()
        if sound_set is None or self.current_work_item is None:
            self.rvc_action.set_status("No output.")
            return
        if not self.settings.rvc.voice_model:
            self.rvc_action.set_status("Select model.")
            return

        self.rvc_action.set_running(True)
        self.rvc_action.set_progress(8)
        self.rvc_action.set_status("Converting")
        scope = WorkTaskScope(self.current_work_item.id)
        settings = settings_for_managed_rvc_runtime(
            self.settings.rvc,
            RVC_RUNTIME_DIR,
        )
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

    def _conversion_input_sound_set(self) -> OutputSoundSet | None:
        session = MainWindow._work_convert_session(self)
        version = session.input_version()
        job_dir = (
            version.job_dir
            if version is not None
            else session.selected_input_job_dir
        )
        if job_dir is None:
            return None
        return load_output_sound_set(job_dir, self.settings.output_root)

    def _on_rvc_succeeded(self, scope: WorkTaskScope, job_dir: Path, result: object) -> None:
        output_path = getattr(result, "output_path", None)
        should_monitor = scope.is_current(self.current_work_item)
        if isinstance(output_path, Path):
            if isinstance(result, RvcConversionResult):
                try:
                    project = self.vocal_project_store.register_take(
                        job_dir,
                        output_path,
                        conversion=VocalConversionSettings(
                            voice_model=result.voice_model,
                            index_file=result.index_file,
                            pitch=result.pitch,
                            requested_device=result.requested_device,
                            effective_device=result.effective_device,
                            f0_method=result.f0_method,
                            inference=result.inference,
                        ),
                    )
                    MainWindow._work_convert_session(self).remember_project(
                        job_dir,
                        project,
                    )
                except Exception as exc:
                    self._logger.warning("Could not register vocal take metadata: %s", exc)
        current_job_dir = MainWindow._work_output_session(self).job_dir
        preferred_job_dir = current_job_dir or (
            job_dir if scope.is_current(self.current_work_item) else None
        )
        self._refresh_output_sets(
            preferred_job_dir=preferred_job_dir,
            select_fallback=preferred_job_dir is not None,
        )
        if should_monitor and isinstance(output_path, Path):
            self._activate_vocal_converted_version(output_path)
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

        if (
            self._studio_playback_queue_dirty
            and self.page_stack.currentIndex() == PAGE_STUDIO
        ):
            self._refresh_output_playback_queue(WorkspacePlaybackScope.STUDIO)
            self._studio_playback_queue_dirty = False

        if self.current_playback_queue is None:
            self._sync_playback_queue_for_page(self.page_stack.currentIndex(), force=True)
        if self.current_playback_queue is None:
            work_song_id = self.current_work_item.id if self.current_work_item is not None else "-"
            self._logger.warning(
                "Playback queue unavailable: page=%s work_song=%s output_set=%s",
                self.page_stack.currentIndex(),
                work_song_id,
                self.current_output_set.job_dir if self.current_output_set is not None else "-",
            )
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
            is_studio = (
                queue.scope == WorkspacePlaybackScope.STUDIO.value
                and bool(self._studio_playback_sources)
            )
            prepared: PreparedPlaybackAudio | None = None
            if is_studio:
                preview_paths = queue.paths
                if self.player.has_prepared_audio():
                    duration_ms = queue.duration_ms
                else:
                    prepared = prepare_studio_playback_audio(self._studio_playback_sources)
                    duration_ms = prepared.duration_ms
                    queue = queue.with_duration(duration_ms)
            else:
                preview_paths = tuple(prepare_preview_audio(path) for path in queue.paths)
                duration_ms = max(self.player.duration_ms(path) for path in preview_paths)
                queue = queue.with_duration(duration_ms)
            start_ms = max(0, min(start_ms, queue.duration_ms))
            if start_ms >= queue.duration_ms:
                start_ms = 0
            self._logger.info(
                "Starting playback: context=%s scope=%s source=%s tracks=%s start_ms=%s",
                queue.context,
                queue.scope or "-",
                queue.source_id,
                len(preview_paths),
                start_ms,
            )
            if is_studio and prepared is None:
                self.player.resume(start_ms, queue.volumes)
            elif is_studio:
                self.player.play_prepared(prepared, start_ms=start_ms, volumes=queue.volumes)
            else:
                self.player.play(preview_paths, start_ms=start_ms, volumes=queue.volumes)
        except Exception as exc:
            self._handle_playback_error(queue, exc)
            return

        session = MainWindow._playback_session(self)
        session.refresh_queue(queue, position_ms=start_ms)
        MainWindow._sync_playback_session_state(self, session)
        if queue.context == "output":
            _set_optional_label(self.output_status_label, "")
        elif queue.context == "library":
            _set_optional_label(self.library_status_label, "")
        self._refresh_playback_ui(is_playing=True)
        self._update_output_playheads(start_ms, queue.duration_ms)
        self.playback_timer.start()

    def _pause_playback(self) -> None:
        session = MainWindow._playback_session(self)
        session.set_position_ms(self.player.position_ms())
        MainWindow._sync_playback_session_state(self, session)
        self.player.pause()
        self.playback_timer.stop()
        self._refresh_playback_ui(is_playing=False)
        self._update_output_playheads(self._playback_position_ms)

    def _seek_global_playback(self, position_ms: int) -> None:
        queue = self.current_playback_queue
        if queue is None:
            return
        session = MainWindow._playback_session(self)
        session.set_position_ms(position_ms)
        MainWindow._sync_playback_session_state(self, session)
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
        scope = self._workspace_scope_for_page(self.page_stack.currentIndex())
        if scope is None:
            return
        queue = self._workspace_playback_queue(scope)
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
        self._sync_result_playback_settings()
        self._queue_current_studio_session_save()
        self._refresh_output_playback_queue()

    def _on_result_playback_settings_changed(
        self,
        track_id: str,
        muted: bool,
        volume_percent: int,
    ) -> None:
        if self.page_stack.currentIndex() == PAGE_CONVERSION:
            self._refresh_output_playback_queue(WorkspacePlaybackScope.CONVERSION)
            return
        track = self._output_track(track_id)
        if track is None:
            return
        track.set_mix_state(muted=muted, volume_percent=volume_percent)
        self._on_output_playback_settings_changed()

    def _on_output_track_source_changed(self) -> None:
        if self.current_output_set is not None:
            path = self.converted_track.current_path()
            convert_session = MainWindow._work_convert_session(self)
            job_dir = convert_session.job_dir_for_converted_path(
                path,
                fallback_job_dir=self.current_output_set.job_dir,
            )
            if job_dir is None:
                self._refresh_output_playback_queue()
                return
            try:
                project = self.vocal_project_store.set_active_take(job_dir, path)
                convert_session.remember_project(job_dir, project)
            except Exception as exc:
                self._logger.warning("Could not persist active vocal take: %s", exc)
            song = self.library.activate_converted_output(job_dir, path)
            if song is not None:
                self._song_items_by_id[song.id] = song
                if self.current_work_item is not None and self.current_work_item.id == song.id:
                    self._assign_work_item(song, persist=False)
            convert_session.select_converted_path(path)
            self.vocal_results_panel.select_converted(path)
            self.conversion_result_browser.select_converted(path)
            MainWindow._sync_conversion_context_from_session(self)
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
            self._sync_result_playback_settings()
            item = self.current_song or self.current_work_item
            try:
                assets = self.library.studio_assets(item.id) if item is not None else ()
            except KeyError:
                assets = ()
            self.studio_editor.set_context(session, assets)
            self._studio_playback_queue_dirty = False
            self._studio_playback_sources = ()
            if self.page_stack.currentIndex() == PAGE_STUDIO:
                self._sync_idle_studio_transport()
        finally:
            self._is_loading_studio_session = False

    def _sync_result_playback_settings(self) -> None:
        for track_id, track in (
            ("original", self.vocal_track),
            ("instrumental", self.instrumental_track),
            ("converted", self.converted_track),
        ):
            self.separation_results_panel.set_mix_state(
                track_id,
                muted=track.is_muted(),
                volume_percent=track.volume_percent(),
            )

    def _output_track(self, track_id: str) -> TrackRow | None:
        return {
            "original": self.vocal_track,
            "instrumental": self.instrumental_track,
            "converted": self.converted_track,
        }.get(track_id)

    def _queue_current_studio_session_save(self) -> None:
        if self._is_loading_studio_session or self.current_output_set is None:
            return
        item = self.current_song or self.current_work_item
        if item is None:
            return
        session = self._studio_session_from_tracks()
        if session.tracks and session != self.studio_editor.session():
            try:
                assets = self.library.studio_assets(item.id)
            except KeyError:
                assets = ()
            self.studio_editor.set_context(session, assets)
        self.studio_session_autosave.queue(item.id, session)

    def _studio_session_from_tracks(self) -> StudioSession:
        session = self.studio_editor.session()
        if not session.tracks:
            return StudioSession(
                original_vocal=_studio_track_state(self.vocal_track),
                instrumental=_studio_track_state(self.instrumental_track),
                converted_vocal=_studio_track_state(self.converted_track),
            )
        rows = {
            "original_vocal": self.vocal_track,
            "instrumental": self.instrumental_track,
            "converted_vocal": self.converted_track,
        }
        for track in session.tracks:
            row = rows.get(track.role)
            if row is not None:
                session = set_studio_track_mix(
                    session,
                    track.track_id,
                    muted=row.is_muted(),
                    volume_percent=row.volume_percent(),
                )
        return session

    def _on_studio_editor_session_changed(
        self,
        session: StudioSession,
        requires_render: bool,
    ) -> None:
        if self._is_loading_studio_session:
            return
        self._is_loading_studio_session = True
        try:
            self.vocal_track.set_mix_state(
                muted=session.state_for("original_vocal").muted,
                volume_percent=session.state_for("original_vocal").volume_percent,
            )
            self.instrumental_track.set_mix_state(
                muted=session.state_for("instrumental").muted,
                volume_percent=session.state_for("instrumental").volume_percent,
            )
            self.converted_track.set_mix_state(
                muted=session.state_for("converted_vocal").muted,
                volume_percent=session.state_for("converted_vocal").volume_percent,
            )
            self._sync_result_playback_settings()
        finally:
            self._is_loading_studio_session = False
        item = self.current_song or self.current_work_item
        if item is not None:
            self.studio_session_autosave.queue(item.id, session)
        queue = self.current_playback_queue
        if (
            item is None
            or queue is None
            or queue.scope != WorkspacePlaybackScope.STUDIO.value
            or queue.source_id != f"studio:{item.id}"
        ):
            return

        try:
            sources = self.library.studio_mix_sources(item.id, session)
        except (AudioExportError, KeyError, OSError, ValueError) as exc:
            self.studio_editor.set_status(_last_error_line(str(exc)))
            return
        if not sources:
            self._studio_playback_sources = ()
            self._studio_playback_queue_dirty = False
            self._stop_playback(clear_queue=True)
            self.studio_editor.set_status(tr("Add at least one audible clip to the Studio timeline."))
            return
        previous_sources = self._studio_playback_sources
        same_layout = bool(previous_sources) and (
            studio_source_layout_signature(previous_sources)
            == studio_source_layout_signature(sources)
        )
        was_playing = self.player.is_playing()
        position_ms = self.player.position_ms() if was_playing else self._playback_position_ms
        refreshed_queue = self._studio_playback_queue(item.id, session, sources)
        self._studio_playback_sources = sources
        playback_session = MainWindow._playback_session(self)
        playback_session.refresh_queue(refreshed_queue, position_ms=position_ms)
        MainWindow._sync_playback_session_state(self, playback_session)

        live_updated = False
        if same_layout:
            live_updated = self.player.set_effect_chains(studio_effect_chains(sources))
            if live_updated:
                self.player.set_volumes(refreshed_queue.volumes)

        needs_prepare = (
            self._studio_playback_queue_dirty
            or requires_render
            or not same_layout
            or (was_playing and not live_updated)
        )
        if was_playing and needs_prepare:
            self._studio_playback_queue_dirty = True
            self._queue_studio_playback_prepare(item.id, session, sources)
        else:
            self._studio_playback_queue_dirty = False
            if needs_prepare:
                self.player.stop()
        self.studio_editor.set_status("")
        self._refresh_playback_ui(is_playing=was_playing)
        self._update_output_playheads(self._playback_position_ms, refreshed_queue.duration_ms)

    def _queue_studio_playback_prepare(
        self,
        song_id: str,
        session: StudioSession,
        sources: tuple[AudioMixSource, ...],
    ) -> None:
        self._studio_playback_prepare_generation += 1
        self._studio_playback_prepare_request = (
            self._studio_playback_prepare_generation,
            song_id,
            session,
            sources,
        )
        self._studio_playback_prepare_timer.start()

    def _start_studio_playback_prepare(self) -> None:
        if self._studio_playback_prepare_worker is not None:
            return
        request = self._studio_playback_prepare_request
        if request is None:
            return
        self._studio_playback_prepare_request = None
        generation, song_id, session, sources = request

        def prepare(_progress) -> PreparedPlaybackAudio:
            return prepare_studio_playback_audio(sources)

        worker = TaskWorker(prepare)
        self._studio_playback_prepare_worker = worker
        self._workers.append(worker)

        def complete(result: object) -> None:
            if (
                generation != self._studio_playback_prepare_generation
                or self._studio_playback_prepare_request is not None
            ):
                return
            if not isinstance(result, PreparedPlaybackAudio):
                return
            self._apply_studio_playback_prepare(
                song_id,
                session,
                sources,
                result,
            )

        def failed(error: str) -> None:
            if generation != self._studio_playback_prepare_generation:
                return
            self._logger.warning("Studio playback preparation failed: %s", _last_error_line(error))
            self.studio_editor.set_status(_last_error_line(error))

        def cleanup() -> None:
            if self._studio_playback_prepare_worker is worker:
                self._studio_playback_prepare_worker = None
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()
            if self._studio_playback_prepare_request is not None:
                self._studio_playback_prepare_timer.start(0)

        worker.succeeded.connect(complete)
        worker.failed.connect(failed)
        worker.finished.connect(cleanup)
        worker.start()

    def _apply_studio_playback_prepare(
        self,
        song_id: str,
        session: StudioSession,
        sources: tuple[AudioMixSource, ...],
        prepared: PreparedPlaybackAudio,
    ) -> bool:
        item = self.current_song or self.current_work_item
        queue = self.current_playback_queue
        if (
            item is None
            or item.id != song_id
            or self.studio_editor.session() != session
            or queue is None
            or queue.scope != WorkspacePlaybackScope.STUDIO.value
            or queue.source_id != f"studio:{song_id}"
        ):
            return False

        duration_ms = prepared.duration_ms
        was_playing = self.player.is_playing()
        position_ms = self.player.position_ms() if was_playing else self._playback_position_ms
        refreshed_queue = self._studio_playback_queue(song_id, session, sources).with_duration(
            duration_ms
        )
        self._studio_playback_sources = sources
        playback_session = MainWindow._playback_session(self)
        playback_session.refresh_queue(refreshed_queue, position_ms=position_ms)
        MainWindow._sync_playback_session_state(self, playback_session)
        self._studio_playback_queue_dirty = False
        self.studio_editor.set_status("")
        if was_playing:
            if not self.player.replace_prepared(prepared, refreshed_queue.volumes):
                self._play_current_queue(self._playback_position_ms)
            else:
                self._refresh_playback_ui(is_playing=True)
                self._update_output_playheads(self._playback_position_ms, duration_ms)
        else:
            self.player.set_prepared(prepared, refreshed_queue.volumes)
            self._refresh_playback_ui(is_playing=False)
            self._update_output_playheads(self._playback_position_ms, duration_ms)
        return True

    @staticmethod
    def _studio_playback_queue(
        song_id: str,
        session: StudioSession,
        sources: tuple[AudioMixSource, ...],
    ) -> PlaybackQueue:
        duration_ms = studio_playback_duration_ms(
            sources,
            minimum_ms=session_duration_ms(session),
        )
        return PlaybackQueue(
            context="output",
            source_id=f"studio:{song_id}",
            title=scope_label(WorkspacePlaybackScope.STUDIO),
            paths=tuple(source.path for source in sources),
            volumes=tuple(source.volume for source in sources),
            duration_ms=duration_ms,
            scope=WorkspacePlaybackScope.STUDIO.value,
        )

    def _seek_studio_timeline(self, position_ms: int) -> None:
        if (
            self.current_playback_queue is not None
            and self.current_playback_queue.scope == WorkspacePlaybackScope.STUDIO.value
        ):
            self._seek_global_playback(position_ms)
            return
        playback_session = MainWindow._playback_session(self)
        playback_session.set_position_ms(position_ms)
        MainWindow._sync_playback_session_state(self, playback_session)
        self.studio_editor.set_playhead(self._playback_position_ms)
        duration_ms = session_duration_ms(self.studio_editor.session())
        self.studio_transport_bar.set_position(self._playback_position_ms, duration_ms)
        item = self.current_song or self.current_work_item
        if item is not None:
            playback_session.remember_position(
                "output",
                f"studio:{item.id}",
                self._playback_position_ms,
                duration_ms=duration_ms,
            )

    def _prepare_studio_playback_surface(self) -> None:
        queue = self.current_playback_queue
        if queue is not None and queue.scope == WorkspacePlaybackScope.STUDIO.value:
            self._refresh_playback_ui(is_playing=self.player.is_playing())
            return
        if queue is not None:
            self._suspend_playback()
        self._sync_idle_studio_transport()

    def _sync_idle_studio_transport(self) -> None:
        duration_ms = session_duration_ms(self.studio_editor.session())
        position_ms = max(0, min(self._playback_position_ms, duration_ms))
        self.studio_transport_bar.set_queue(duration_ms)
        self.studio_transport_bar.set_position(position_ms, duration_ms)
        self.studio_transport_bar.set_playing(False)
        self.studio_editor.set_playhead(position_ms)

    def _on_studio_session_save_failed(self, error: str) -> None:
        _set_optional_label(self.output_status_label, f"Session failed: {_last_error_line(error)}")

    def _sync_global_playback_state(self) -> None:
        queue = self.current_playback_queue
        if queue is None:
            self._stop_playback(clear_queue=True)
            return
        if not self.player.is_playing():
            self.playback_timer.stop()
            playback_session = MainWindow._playback_session(self)
            playback_session.set_position_ms(min(self.player.position_ms(), queue.duration_ms))
            MainWindow._sync_playback_session_state(self, playback_session)
            self._refresh_playback_ui(is_playing=False)
            self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
            return

        playback_session = MainWindow._playback_session(self)
        playback_session.set_position_ms(self.player.position_ms())
        MainWindow._sync_playback_session_state(self, playback_session)
        if self._playback_position_ms >= queue.duration_ms:
            self.player.pause()
            self.playback_timer.stop()
            playback_session.set_position_ms(queue.duration_ms)
            MainWindow._sync_playback_session_state(self, playback_session)
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
        previous_position = (
            self.player.position_ms() if self.player.is_playing() else self._playback_position_ms
        )
        session = MainWindow._playback_session(self)
        session.set_queue(
            queue,
            position_ms=position_ms,
            previous_position_ms=previous_position,
        )
        self.player.stop()
        self.playback_timer.stop()
        MainWindow._sync_playback_session_state(self, session)
        if queue is None:
            MainWindow._clear_result_transports(self)
            self._sync_playback_surfaces()
            self._update_output_playheads(0, 0)
            return

        self._library_preview_song_id = queue.source_id if queue.context == "library" else ""
        if queue.context == "library":
            MainWindow._clear_result_transports(self)

        self._refresh_playback_ui(is_playing=False)
        self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
        if auto_play:
            self._play_current_queue(self._playback_position_ms)

    def _stop_playback(self, update_player: bool = True, *, clear_queue: bool = False) -> None:
        queue = self.current_playback_queue
        if update_player:
            self.player.stop()
        self.playback_timer.stop()
        session = MainWindow._playback_session(self)
        if clear_queue:
            session.clear_queue()
        else:
            session.stop()
        MainWindow._sync_playback_session_state(self, session)
        if clear_queue:
            MainWindow._clear_result_transports(self)
            if queue is not None and queue.context == "library":
                self._library_preview_song_id = ""
            elif queue is not None and queue.context == "library_asset":
                self.library_details_panel.set_preview_expanded(Path(queue.source_id), False)
            elif queue is not None and queue.context == "export":
                self.export_page.set_preview_expanded(Path(queue.source_id), False)
            self._sync_playback_surfaces()
            self._update_output_playheads(0, 0)
            return
        self._refresh_playback_ui(is_playing=False)
        duration = self.current_playback_queue.duration_ms if self.current_playback_queue is not None else 0
        self._update_output_playheads(0, duration)

    def _suspend_playback(self) -> None:
        queue = self.current_playback_queue
        if queue is not None:
            position_ms = (
                self.player.position_ms()
                if self.player.is_playing()
                else self._playback_position_ms
            )
            session = MainWindow._playback_session(self)
            session.suspend(position_ms)
            MainWindow._sync_playback_session_state(self, session)
            if queue.context == "library":
                self._set_library_preview_expanded(queue.source_id, False)
            elif queue.context == "library_asset":
                self.library_details_panel.set_preview_expanded(Path(queue.source_id), False)
            elif queue.context == "export":
                self.export_page.set_preview_expanded(Path(queue.source_id), False)
        self._stop_playback(clear_queue=True)

    def _resume_position(self, queue: PlaybackQueue) -> int:
        return MainWindow._playback_session(self).resume_position(queue)

    def _refresh_output_playback_queue(
        self,
        scope: WorkspacePlaybackScope | None = None,
    ) -> None:
        selected_scope = scope or self._workspace_scope_for_page(self.page_stack.currentIndex())
        if selected_scope is None:
            return
        queue = self._workspace_playback_queue(selected_scope)
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
                session = MainWindow._playback_session(self)
                session.set_queue(
                    queue,
                    position_ms=session.resume_position(queue),
                    previous_position_ms=position_ms,
                )
                self.player.stop()
                self.playback_timer.stop()
                MainWindow._sync_playback_session_state(self, session)
                self._refresh_playback_ui(is_playing=False)
                self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
                return
            session = MainWindow._playback_session(self)
            session.refresh_queue(queue, position_ms=position_ms)
            MainWindow._sync_playback_session_state(self, session)
            self._refresh_playback_ui(is_playing=was_playing)
            self._update_output_playheads(self._playback_position_ms, queue.duration_ms)
            if was_playing:
                if queue.has_same_sources(current_queue) and not queue.reload_on_refresh:
                    try:
                        self.player.set_volumes(queue.volumes)
                    except AudioPlaybackError as exc:
                        _set_optional_label(self.output_status_label, f"Volume failed: {_last_error_line(str(exc))}")
                else:
                    self._play_current_queue(self._playback_position_ms)
            return

        if self.page_stack.currentIndex() in {PAGE_SEPARATION, PAGE_CONVERSION, PAGE_STUDIO} and not self.player.is_playing():
            self._set_playback_queue(queue, position_ms=self._resume_position(queue))
            return

        self._update_output_playheads(0, queue.duration_ms)

    def _sync_playback_queue_for_page(self, index: int, *, force: bool = False) -> None:
        if self.player.is_playing() and not force:
            return
        if index == PAGE_LIBRARY and self._library_preview_song_id:
            self._load_library_playback_queue(
                self._song_items_by_id.get(self._library_preview_song_id)
            )
        else:
            scope = self._workspace_scope_for_page(index)
            if scope is not None:
                self._refresh_output_playback_queue(scope)

    def _refresh_playback_ui(self, *, is_playing: bool) -> None:
        queue = self.current_playback_queue
        if queue is None:
            MainWindow._clear_result_transports(self)
            if self.page_stack.currentIndex() == PAGE_STUDIO:
                self._sync_idle_studio_transport()
            else:
                self.studio_transport_bar.clear()
            self._sync_playback_surfaces()
            self._sync_video_playback(False)
            return

        if queue.context == "library":
            _item, row = self._library_row(queue.source_id)
            if row is not None:
                row.set_preview_queue(queue.duration_ms)
                row.set_preview_position(self._playback_position_ms, queue.duration_ms)
                row.set_preview_playing(is_playing)
        elif queue.context == "library_asset":
            path = Path(queue.source_id)
            self.library_details_panel.set_preview_queue(path, queue.duration_ms)
            self.library_details_panel.set_preview_position(
                path,
                self._playback_position_ms,
                queue.duration_ms,
            )
            self.library_details_panel.set_preview_playing(path, is_playing)
        elif queue.context == "export":
            path = Path(queue.source_id)
            self.export_page.set_preview_queue(path, queue.duration_ms)
            self.export_page.set_preview_position(
                path,
                self._playback_position_ms,
                queue.duration_ms,
            )
            self.export_page.set_preview_playing(path, is_playing)
        elif queue.scope == WorkspacePlaybackScope.STUDIO.value:
            self.studio_transport_bar.set_queue(queue.duration_ms)
            self.studio_transport_bar.set_position(
                self._playback_position_ms,
                queue.duration_ms,
            )
            self.studio_transport_bar.set_playing(is_playing)
        else:
            transport = MainWindow._result_transport_for_scope(
                self,
                self._workspace_scope_for_queue(queue)
            )
            MainWindow._clear_result_transports(
                self,
                except_transport=transport,
            )
            if transport is not None:
                transport.set_queue(queue.duration_ms)
                transport.set_position(self._playback_position_ms, queue.duration_ms)
                transport.set_playing(is_playing)
        self._sync_playback_surfaces()
        self._sync_video_playback(is_playing)

    def _current_playback_context(self) -> str:
        return MainWindow._playback_session(self).current_context()

    def _is_playing_context(self, context: str) -> bool:
        return self.player.is_playing() and MainWindow._playback_session(self).is_context(context)

    def _handle_playback_error(self, queue: PlaybackQueue, error: Exception) -> None:
        self._logger.error(
            "Playback failed: context=%s scope=%s source=%s paths=%s error=%s",
            queue.context,
            queue.scope or "-",
            queue.source_id,
            tuple(str(path) for path in queue.paths),
            error,
        )
        message = f"Playback failed: {_last_error_line(str(error))}"
        if queue.context == "export":
            self.export_page.set_audio_status(message)
        else:
            target_label = self.output_status_label if queue.context == "output" else self.library_status_label
            _set_optional_label(target_label, message)
        self._stop_playback()

    def _playback_track_paths(
        self,
        scope: WorkspacePlaybackScope | None = None,
    ) -> list[tuple[Path, float]]:
        if scope is WorkspacePlaybackScope.CONVERSION:
            panel = getattr(self, "vocal_results_panel", None)
            playback_tracks = getattr(panel, "playback_tracks", None)
            if callable(playback_tracks):
                return list(playback_tracks())
        tracks: list[tuple[Path, float]] = []
        separation_paths = getattr(self, "_separation_preview_paths", {})
        if scope is None:
            track_rows = (("", track) for track in self.output_tracks)
        else:
            output_track = getattr(self, "_output_track", None)
            track_rows = (
                (track_id, output_track(track_id))
                for track_id in scope_track_ids(scope)
            )
        for track_id, track in track_rows:
            if track is None:
                continue
            path = (
                separation_paths.get(track_id)
                if scope is WorkspacePlaybackScope.SEPARATION
                and track_id in separation_paths
                else track.current_path()
            )
            if path is not None:
                volume = 0.0 if track.is_muted() else track.volume()
                tracks.append((path, volume))
        return tracks

    def _loaded_track_paths(
        self,
        scope: WorkspacePlaybackScope | None = None,
    ) -> list[Path]:
        return [path for path, _volume in self._playback_track_paths(scope)]

    def _output_playback_queue(self) -> PlaybackQueue | None:
        return self._workspace_playback_queue(WorkspacePlaybackScope.STUDIO)

    def _workspace_scope_for_page(self, page_index: int) -> WorkspacePlaybackScope | None:
        return {
            PAGE_SEPARATION: WorkspacePlaybackScope.SEPARATION,
            PAGE_CONVERSION: WorkspacePlaybackScope.CONVERSION,
            PAGE_STUDIO: WorkspacePlaybackScope.STUDIO,
        }.get(page_index)

    def _workspace_playback_queue(
        self,
        scope: WorkspacePlaybackScope,
    ) -> PlaybackQueue | None:
        if scope is WorkspacePlaybackScope.STUDIO:
            return self._studio_timeline_playback_queue()
        tracks = self._playback_track_paths(scope)
        duration_ms = self._duration_ms_for_paths([path for path, _volume in tracks])
        if not tracks or duration_ms <= 0:
            item = self.current_work_item
            if item is None or item.kind != "source":
                return None
            duration_ms = self._duration_ms_for_paths([item.path])
            if duration_ms <= 0:
                return None
            return PlaybackQueue(
                context="output",
                source_id=f"source:{item.id}",
                title=item.title,
                paths=(item.path,),
                volumes=(1.0,),
                duration_ms=duration_ms,
                scope=scope.value,
            )
        work_item = getattr(self, "current_work_item", None)
        source_id = (
            f"separation:{work_item.id}"
            if scope is WorkspacePlaybackScope.SEPARATION and work_item is not None
            else "separation:"
            + (
                str(self.current_output_set.job_dir)
                if self.current_output_set is not None
                else "preview"
            )
            if scope is WorkspacePlaybackScope.SEPARATION
            else str(self.current_output_set.job_dir)
            if self.current_output_set is not None
            else ""
        )
        return PlaybackQueue(
            context="output",
            source_id=source_id,
            title=scope_label(scope),
            paths=tuple(path for path, _volume in tracks),
            volumes=tuple(volume for _path, volume in tracks),
            duration_ms=duration_ms,
            scope=scope.value,
        )

    def _studio_timeline_playback_queue(self) -> PlaybackQueue | None:
        item = self.current_song or self.current_work_item
        if item is None:
            return None
        session = self.studio_editor.session()
        duration_ms = session_duration_ms(session)
        if duration_ms <= 0:
            self.studio_editor.set_status(tr("Add a sound to the timeline."))
            return None
        try:
            sources = self.library.studio_mix_sources(item.id, session)
        except (AudioExportError, KeyError, OSError, ValueError) as exc:
            self.studio_editor.set_status(_last_error_line(str(exc)))
            return None
        if not sources:
            self.studio_editor.set_status(tr("Add at least one audible clip to the Studio timeline."))
            return None
        self._studio_playback_sources = sources
        self.studio_editor.set_status("")
        return self._studio_playback_queue(item.id, session, sources)

    @staticmethod
    def _direct_studio_preview_duration(sources: tuple[AudioMixSource, ...]) -> int:
        if not sources:
            return 0
        duration_ms = 0
        for source in sources:
            if source.effects:
                return 0
            if source.timeline_start_ms != 0 or source.source_start_ms != 0:
                return 0
            if not 0.0 <= source.volume <= 2.0:
                return 0
            try:
                source_duration = read_audio_metadata(source.path).duration_ms
            except Exception:
                return 0
            source_end = source.source_end_ms
            if source_end is not None and abs(source_end - source_duration) > 10:
                return 0
            duration_ms = max(duration_ms, source_duration)
        return duration_ms

    def _update_output_playheads(self, position_ms: int, duration_ms: int | None = None) -> None:
        queue = self.current_playback_queue if self._current_playback_context() == "output" else None
        duration = duration_ms if duration_ms is not None else (queue.duration_ms if queue is not None else 0)
        position = max(0, min(position_ms, duration)) if duration > 0 else 0
        ratio = position / duration if duration > 0 else 0.0
        scope = self._workspace_scope_for_queue(queue)
        if scope is None:
            self.separation_results_panel.set_playhead_ratio(0.0)
            self.vocal_results_panel.set_playhead_ratio(0.0)
            studio_editor = getattr(self, "studio_editor", None)
            if studio_editor is not None:
                studio_editor.set_playhead(0)
            for track in self.output_tracks:
                track.set_playhead_ratio(0.0)
        elif scope is WorkspacePlaybackScope.SEPARATION:
            self.separation_results_panel.set_playhead_ratio(ratio)
        elif scope is WorkspacePlaybackScope.CONVERSION:
            self.vocal_results_panel.set_playhead_ratio(ratio)
        elif scope is WorkspacePlaybackScope.STUDIO:
            studio_editor = getattr(self, "studio_editor", None)
            if studio_editor is not None:
                studio_editor.set_playhead(position)

    @staticmethod
    def _workspace_scope_for_queue(
        queue: PlaybackQueue | None,
    ) -> WorkspacePlaybackScope | None:
        if queue is None or queue.context != "output":
            return None
        try:
            return WorkspacePlaybackScope(queue.scope or WorkspacePlaybackScope.STUDIO.value)
        except ValueError:
            return None

    def _loaded_output_duration_ms(self) -> int:
        if hasattr(self, "studio_editor"):
            return session_duration_ms(self.studio_editor.session())
        return self._duration_ms_for_paths(self._loaded_track_paths(WorkspacePlaybackScope.STUDIO))

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
        output_available = MainWindow._work_output_session(self).output_available(
            song.output_job_dir,
            self.settings.output_root,
        )
        capabilities = build_work_song_capabilities(
            output_available=output_available,
            item=song,
        )
        has_local_media = video_source.path is not None and video_source.path.is_file()
        try:
            export_duration_ms = read_audio_metadata(song.path).duration_ms
        except Exception:
            export_duration_ms = 0
        self.export_page.set_exports(audio_exports, video_exports, export_dir)
        self.export_page.set_target_song(
            song.id,
            audio_enabled=capabilities.can_export,
            video_enabled=capabilities.can_export and has_local_media,
            duration_ms=export_duration_ms,
        )
        if self._current_playback_context() == "export":
            self._refresh_playback_ui(is_playing=self.player.is_playing())

    def _on_export_song_changed(self, song_id: str) -> None:
        if self._current_playback_context() == "export":
            self._suspend_playback()
        self._export_song_id = song_id
        self._refresh_export_page()

    def _is_export_song(self, song_id: str) -> bool:
        return bool(song_id) and self._export_song_id == song_id

    def _start_audio_mix_export(self, song_id: str, settings: AudioExportSettings) -> None:
        song = self._song_items_by_id.get(song_id)
        if song is None:
            self.export_page.set_audio_status("Select a song.")
            return

        self.studio_session_autosave.flush()
        self.export_page.set_audio_running(True)
        self.export_page.set_audio_progress(0)
        self.export_page.set_audio_status(f"Exporting {settings.output_label}")
        scope = WorkTaskScope(song_id)
        worker = TaskWorker(
            lambda progress: self.library.export_audio_mix(song_id, settings, progress)
        )
        self._run_worker(
            worker,
            lambda result: self._on_audio_mix_export_succeeded(scope, result),
            lambda error: self._on_audio_mix_export_failed(scope, error),
            self.export_page.audio_controls,
            task_title="Export Mix",
            task_detail=f"{song.title} / {settings.output_label}",
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
        export_label = f"{item.title} - {_track_export_role(self.current_output_set, path)}"
        worker = TaskWorker(
            lambda progress: _run_with_progress(
                lambda: export_audio_file(export_label, path, output_dir),
                progress,
            )
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

    def _open_export_drive_share(self, path: Path) -> None:
        self.google_drive.open_export_share(path)

    def _open_model_drive_share(self, record: RvcModelRecord) -> None:
        self.google_drive.open_model_share(record)

    def _open_model_work_drive_share(self, record: RvcModelRecord) -> None:
        self.google_drive.open_model_work_share(record)

    def _delete_export_drive_share(self, path: Path) -> None:
        if self._confirm_drive_share_delete(path.name):
            self.google_drive.delete_export_share(path)

    def _rename_export(self, path: Path, name: str) -> None:
        song_id = self._export_song_id
        if not song_id:
            return
        resolved = path.expanduser().resolve()
        queue = self.current_playback_queue
        if queue is not None and queue.context == "export" and queue.source_id == str(resolved):
            MainWindow._playback_session(self).pop_resume_position("export", str(resolved))
            self._stop_playback(clear_queue=True)
        try:
            renamed = self.library.rename_export(song_id, resolved, name)
            self.google_drive.move_export_share(resolved, renamed)
        except Exception as exc:
            self.export_page.set_audio_status(
                f"Rename failed: {_last_error_line(str(exc))}",
                str(exc),
            )
            return
        self._refresh_export_page()

    def _delete_model_drive_share(self, record: RvcModelRecord) -> None:
        if self._confirm_drive_share_delete(record.title):
            self.google_drive.delete_model_share(record)

    def _delete_model_work_drive_share(self, record: RvcModelRecord) -> None:
        if self._confirm_drive_share_delete(record.title):
            self.google_drive.delete_model_work_share(record)

    def _confirm_drive_share_delete(self, title: str) -> bool:
        return ConfirmationDialog.confirm(
            self,
            tr("Remove Google Drive Share"),
            tr(
                "Delete '{name}' from Google Drive? The local file will not be deleted.",
                name=title,
            ),
            APP_ICON_PATH,
            theme_mode=self.settings.theme_mode,
            accept_label=tr("Delete"),
            cancel_label=tr("Cancel"),
        )

    def _on_drive_share_started(self, target_id: str) -> None:
        if target_id.startswith("model-work::"):
            self.model_workspace_page.set_work_share_started(
                target_id.removeprefix("model-work::")
            )
        else:
            self.model_workspace_page.set_share_started(target_id)
        self.export_page.set_share_started(target_id)

    def _on_drive_share_progress(self, target_id: str, progress: int) -> None:
        if target_id.startswith("model-work::"):
            self.model_workspace_page.set_work_share_progress(
                target_id.removeprefix("model-work::"),
                progress,
            )
        else:
            self.model_workspace_page.set_share_progress(target_id, progress)
        self.export_page.set_share_progress(target_id, progress)

    def _on_drive_share_succeeded(self, target_id: str, _link: str) -> None:
        if target_id.startswith("model-work::"):
            self.model_workspace_page.set_work_share_completed(
                target_id.removeprefix("model-work::")
            )
        else:
            self.model_workspace_page.set_share_completed(target_id)
        self.export_page.set_share_completed(target_id)

    def _on_drive_share_failed(self, target_id: str, error: str) -> None:
        is_model_share = any(
            record.model_id == target_id for record in self.model_workspace.records()
        )
        if target_id.startswith("model-work::"):
            self.model_workspace_page.set_work_share_failed(
                target_id.removeprefix("model-work::")
            )
        else:
            self.model_workspace_page.set_share_failed(target_id)
        self.export_page.set_share_failed(target_id)
        if not target_id.startswith("model-work::") and not is_model_share:
            self.export_page.set_audio_status(error, error)
            self.export_page.set_video_status(error, error)

    def _on_drive_share_deleted(self, target_id: str) -> None:
        if target_id.startswith("model-work::"):
            self.model_workspace_page.set_work_share_deleted(
                target_id.removeprefix("model-work::")
            )
        else:
            self.model_workspace_page.set_share_deleted(target_id)
        self.export_page.set_share_deleted(target_id)

    @staticmethod
    def _playback_session(self) -> PlaybackSession:
        session = getattr(self, "playback_session", None)
        if isinstance(session, PlaybackSession):
            return session
        return PlaybackSession(
            queue=getattr(self, "current_playback_queue", None),
            position_ms=getattr(self, "_playback_position_ms", 0),
            resume_positions=getattr(self, "_playback_resume_positions", {}),
        )

    @staticmethod
    def _sync_playback_session_state(self, session: PlaybackSession) -> None:
        self.current_playback_queue = session.queue
        self._playback_position_ms = session.position_ms
        self._playback_resume_positions = session.resume_positions

    @staticmethod
    def _work_song_session(self) -> WorkSongSession:
        session = getattr(self, "work_song_session", None)
        if isinstance(session, WorkSongSession):
            return session
        return WorkSongSession(
            getattr(self, "work_song_store", None),
            item=getattr(self, "current_work_item", None),
            ready=getattr(self, "_work_song_ready", False),
        )

    @staticmethod
    def _sync_work_song_session_state(self, session: WorkSongSession) -> None:
        self.current_work_item = session.item
        self.current_song = session.source_item
        self._work_song_ready = session.ready

    @staticmethod
    def _work_convert_session(self) -> WorkConvertSession:
        session = getattr(self, "work_convert_session", None)
        if isinstance(session, WorkConvertSession):
            return session
        selected_input = None
        pool = getattr(self, "conversion_input_pool", None)
        if pool is not None:
            selected_version = getattr(pool, "selected_version", None)
            if callable(selected_version):
                version = selected_version()
                selected_input = version.job_dir if version is not None else None
        selected_converted = None
        browser = getattr(self, "conversion_result_browser", None)
        if browser is not None:
            selected_path = getattr(browser, "selected_path", None)
            if callable(selected_path):
                selected_converted = selected_path()
        session = WorkConvertSession(
            selected_input_job_dir=selected_input,
            selected_converted_path=selected_converted,
        )
        setattr(self, "work_convert_session", session)
        return session

    @staticmethod
    def _work_output_session(self) -> WorkOutputSession:
        session = getattr(self, "work_output_session", None)
        if isinstance(session, WorkOutputSession):
            return session
        return WorkOutputSession(getattr(self, "current_output_set", None))

    @staticmethod
    def _sync_work_output_session_state(self, session: WorkOutputSession) -> None:
        self.current_output_set = session.sound_set

    def _start_drive_model_import(self, link: str) -> None:
        self.google_drive.import_model_link(link)

    def _on_drive_models_imported(
        self,
        records: tuple[RvcModelRecord, ...],
    ) -> None:
        self.model_workspace_page.apply_drive_import(records)
        self._refresh_rvc_choices()

    def _use_model_in_convert(self, record: RvcModelRecord) -> None:
        choice = rvc_model_choice_from_record(record, execution_root=RVC_RUNTIME_DIR)
        if choice is None:
            self.model_workspace_page.show_status("This model has no usable inference file.")
            return
        self._apply_rvc_model_choice(choice)
        self._refresh_rvc_choices()
        self.model_workspace_page.show_status(f"{record.title} is active in Convert.")
        self._navigate_to_page(PAGE_CONVERSION)

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
        cancelled_error: Callable[[str], bool] | None = None,
    ) -> None:
        task_id = self.processing_queue.start(task_title, task_detail)
        worker.set_diagnostic_task_id(task_id)
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
            if cancelled_error is not None and cancelled_error(error):
                self.processing_queue.cancel(task_id)
            else:
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


def _check_for_updates(
    manifest_url: str,
    progress: Callable[[int], None],
    *,
    etag: str = "",
    last_modified: str = "",
) -> UpdateCheckOutcome:
    progress(10)
    check = fetch_release_manifest_if_changed(
        manifest_url,
        etag=etag,
        last_modified=last_modified,
    )
    progress(100)
    if check.release is None:
        return UpdateCheckOutcome(
            None,
            check.etag,
            check.last_modified,
            check.not_modified,
        )
    runtime_version = installed_runtime_version(APP_PATHS.runtime_root)
    profile = installed_rvc_runtime_profile(APP_PATHS.runtime_root / "rvc")
    return UpdateCheckOutcome(
        create_update_plan(
            check.release,
            runtime_version=runtime_version,
            runtime_ready=runtime_version is not None,
            desired_rvc_profile=detect_rvc_runtime_profile(),
            installed_rvc_profile=profile.profile if profile else "",
            installed_rvc_profile_version=profile.version if profile else "",
            installed_rvc_preferred_profile=profile.preferred_profile if profile else "",
            installed_rvc_preferred_version=profile.preferred_version if profile else "",
            installed_rvc_failed_fallback_profile=(
                profile.failed_fallback_profile if profile else ""
            ),
            installed_rvc_failed_fallback_version=(
                profile.failed_fallback_version if profile else ""
            ),
        ),
        check.etag,
        check.last_modified,
        check.not_modified,
    )


def _download_update_artifacts(
    plan: UpdatePlan,
    cache_dir: Path,
    progress: Callable[[int], None],
) -> tuple[Path, ...]:
    artifacts = plan.artifacts
    if not artifacts:
        return ()
    destination = cache_dir / "updates" / plan.release.version
    total_size = sum(artifact.size for artifact in artifacts)
    completed_size = 0
    paths: list[Path] = []
    for artifact in artifacts:
        base_size = completed_size
        path = download_artifact(
            artifact,
            destination,
            progress=lambda value, item=artifact, base=base_size: progress(
                int((base + item.size * value / 100) * 100 / total_size)
            ),
        )
        paths.append(path)
        completed_size += artifact.size
    progress(100)
    return tuple(paths)


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


def _resolved_path_key(path: Path | None) -> str:
    return str(path.expanduser().resolve()).casefold() if path is not None else ""


def _convert_with_progress(input_path: Path, output_dir: Path, settings: RvcSettings, progress) -> object:
    progress(12)
    result = convert_vocal_with_rvc(
        input_path,
        output_dir,
        settings,
        progress_callback=lambda value: progress(12 + round(value * 0.86)),
    )
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


def _track_export_role(sound_set: OutputSoundSet | None, path: Path) -> str:
    if sound_set is None:
        return "Audio"
    if _same_path(path, sound_set.vocals_path):
        return "Original Vocal"
    if _same_path(path, sound_set.instrumental_path):
        return "Instrumental"
    if any(_same_path(path, converted) for converted in sound_set.converted_vocal_paths):
        return "Converted Vocal"
    return "Audio"


def _active_vocal_take_path(project: VocalProject) -> Path | None:
    return next(
        (
            take.output_path
            for take in project.takes
            if take.take_id == project.active_take_id
        ),
        None,
    )


def _same_path(first: Path, second: Path) -> bool:
    return first.expanduser().resolve() == second.expanduser().resolve()


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _last_error_line(error: str) -> str:
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"
