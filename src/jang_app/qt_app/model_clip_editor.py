from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.clip_waveform_view import ClipWaveformView, ClipWaveformViewState
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import FeedbackButton, ScrollSafeSlider, ScrollSafeSpinBox, SvgIconButton
from jang_app.services.audio_player import AudioPlayer
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.clip_edit_history import (
    REVIEW_EDITING,
    REVIEW_READY,
    REVIEW_UNREVIEWED,
    TRAINING_MODE_CLIPS,
)
from jang_app.services.model_dataset import ModelDatasetClip, ModelDatasetItem
from jang_app.services.i18n import tr
from jang_app.services.segment_review import (
    SEGMENT_HELD,
    SEGMENT_PENDING,
    SEGMENT_REJECTED,
    SegmentCandidate,
)
from jang_app.services.silence_detection import SpeechRegion


_REVIEW_CONTROL_SIZE = 32
_REVIEW_ACTION_MIN_WIDTH = 72


class ModelClipEditor(QFrame):
    add_clip_requested = Signal(int, int)
    update_clip_requested = Signal(str, int, int)
    split_clip_requested = Signal(str, int)
    analyze_requested = Signal(int, int, int, int)
    use_candidate_requested = Signal(str, int, int)
    candidate_status_requested = Signal(str, str)
    remove_clip_requested = Signal(str)
    undo_requested = Signal()
    redo_requested = Signal()
    reset_requested = Signal()
    ready_requested = Signal()
    navigate_requested = Signal(int)
    close_requested = Signal()
    denoise_requested = Signal(int, int, int)
    remove_denoise_requested = Signal()
    playback_started = Signal()
    playback_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DatasetClipEditor")
        self._item: ModelDatasetItem | None = None
        self._theme_mode = "white"
        self._is_busy = False
        self._has_previous = False
        self._has_next = False
        self._player = AudioPlayer()
        self._play_position_ms = 0
        self._selection_start_ms = 0
        self._selection_end_ms = 0
        self._candidate_filter = SEGMENT_PENDING
        self._preview_version = "original"
        self._noise_sample_start_ms = 0
        self._noise_sample_end_ms = 0
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(50)
        self._playback_timer.timeout.connect(self._sync_playback)
        self._build_ui()
        self._install_shortcuts()

    def _build_ui(self) -> None:
        header = self._build_header()
        self.waveform = ClipWaveformView()
        self.waveform.selection_changed.connect(self._on_selection_changed)
        self.waveform.clip_preview_changed.connect(self._on_clip_preview_changed)
        self.waveform.clip_edit_finished.connect(self._on_clip_edit_finished)
        self.waveform.clip_selected.connect(self._on_waveform_clip_selected)
        self.waveform.seek_requested.connect(self._seek)
        self.waveform.zoom_changed.connect(self.zoom_slider.setValue)

        result_header, result_row = self._build_result_area()
        review_bar = self._build_review_bar()
        self.cleanup_bar = self._build_cleanup_bar()
        self.analysis_bar = self._build_analysis_bar()
        self.secondary_tools = self._build_secondary_tools()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.waveform, 1)
        layout.addLayout(result_header)
        layout.addLayout(result_row)
        layout.addWidget(review_bar)
        layout.addWidget(self.secondary_tools)
        self.setMinimumHeight(420)

    def _build_header(self) -> QHBoxLayout:
        self.title_label = QLabel("Clip Editor")
        self.title_label.setObjectName("DatasetEditorTitle")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("DatasetEditorMeta")
        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        identity.addWidget(self.title_label)
        identity.addWidget(self.detail_label)

        self.review_badge = QLabel("UNREVIEWED")
        self.review_badge.setObjectName("DatasetReviewBadge")
        self.review_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previous_button = _icon_button("arrow_left", "Previous training audio")
        self.previous_button.clicked.connect(lambda: self.navigate_requested.emit(-1))
        self.next_button = _icon_button("arrow_right", "Next training audio")
        self.next_button.clicked.connect(lambda: self.navigate_requested.emit(1))
        self.ready_button = FeedbackButton("Finish  R")
        self.ready_button.setObjectName("DatasetReadyButton")
        _size_review_action(self.ready_button)
        set_translated_tooltip(
            self.ready_button,
            "Mark ready and continue to the next audio (R)",
        )
        self.ready_button.clicked.connect(self.ready_requested.emit)
        self.close_button = _icon_button("close", "Close editor")
        self.close_button.clicked.connect(self.close_requested.emit)

        self.zoom_label = QLabel("1x")
        self.zoom_label.setObjectName("DatasetEditorMeta")
        self.zoom_label.setFixedWidth(28)
        self.zoom_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setObjectName("DatasetZoomSlider")
        self.zoom_slider.setRange(1, 12)
        self.zoom_slider.setValue(1)
        self.zoom_slider.setFixedWidth(140)
        self.zoom_slider.valueChanged.connect(self._set_zoom)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addLayout(identity)
        header.addWidget(self.review_badge)
        header.addStretch(1)
        header.addWidget(QLabel("ZOOM"))
        header.addWidget(self.zoom_slider)
        header.addWidget(self.zoom_label)
        header.addWidget(self.close_button)
        return header

    def _build_review_bar(self) -> QFrame:
        self.review_bar = QFrame()
        self.review_bar.setObjectName("DatasetReviewBar")
        self.play_button = _icon_button("play", "Preview selection (Space)")
        self.play_button.clicked.connect(self._toggle_playback)
        self.play_shortcut_badge = QLabel("SPACE")
        self.play_shortcut_badge.setObjectName("DatasetShortcutKey")
        set_translated_tooltip(
            self.play_shortcut_badge,
            "Preview selection (Space)",
        )
        self.loop_button = _icon_button("repeat", "Loop selection")
        self.loop_button.setCheckable(True)
        self.split_button = _icon_button("split", "Split selected clip at playhead")
        self.split_button.clicked.connect(self._emit_split_clip)
        self.position_label = QLabel("00:00.0")
        self.position_label.setObjectName("DatasetEditorTime")
        self.selection_label = QLabel("Select a range")
        self.selection_label.setObjectName("DatasetEditorSelection")

        layout = QHBoxLayout(self.review_bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(7)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.play_button)
        layout.addWidget(self.play_shortcut_badge)
        layout.addWidget(self.next_button)
        layout.addSpacing(3)
        layout.addWidget(self.action_stack)
        layout.addWidget(self.ready_button)
        layout.addStretch(1)
        layout.addWidget(self.position_label)
        layout.addWidget(self.selection_label)
        layout.addWidget(self.loop_button)
        layout.addWidget(self.split_button)
        return self.review_bar

    def _build_cleanup_bar(self) -> QFrame:
        cleanup_bar = QFrame()
        cleanup_bar.setObjectName("DatasetToolPanel")
        layout = QVBoxLayout(cleanup_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel("NOISE CLEANUP")
        label.setObjectName("DatasetAnalysisLabel")

        source_control = QFrame()
        source_control.setObjectName("DatasetResultTabs")
        source_layout = QHBoxLayout(source_control)
        source_layout.setContentsMargins(2, 2, 2, 2)
        source_layout.setSpacing(0)
        self.original_source_button = FeedbackButton("Original")
        self.denoised_source_button = FeedbackButton("Denoised")
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        for index, button in enumerate((self.original_source_button, self.denoised_source_button)):
            button.setObjectName("DatasetResultTab")
            button.setCheckable(True)
            self.source_button_group.addButton(button, index)
            source_layout.addWidget(button)
        self.original_source_button.setChecked(True)
        self.original_source_button.clicked.connect(lambda: self._set_preview_version("original"))
        self.denoised_source_button.clicked.connect(lambda: self._set_preview_version("denoised"))

        self.set_noise_sample_button = FeedbackButton("Set Noise Sample")
        self.set_noise_sample_button.setObjectName("DatasetEditorSecondaryButton")
        self.set_noise_sample_button.clicked.connect(self._capture_noise_sample)
        self.noise_sample_label = QLabel("")
        self.noise_sample_label.setObjectName("DatasetEditorTime")
        self.clear_noise_sample_button = _icon_button("close", "Clear noise sample", 26)
        self.clear_noise_sample_button.clicked.connect(self._clear_noise_sample)

        self.denoise_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.denoise_slider.setObjectName("DatasetDenoiseSlider")
        self.denoise_slider.setRange(0, 100)
        self.denoise_slider.setValue(50)
        self.denoise_slider.setFixedWidth(160)
        self.denoise_slider.valueChanged.connect(self._refresh_denoise_strength)
        self.denoise_value_label = QLabel("50%")
        self.denoise_value_label.setObjectName("DatasetEditorTime")
        self.denoise_value_label.setFixedWidth(36)
        self.remove_denoise_button = FeedbackButton("Remove Denoise")
        self.remove_denoise_button.setObjectName("DatasetEditorSecondaryButton")
        self.remove_denoise_button.clicked.connect(self.remove_denoise_requested.emit)
        self.apply_denoise_button = FeedbackButton("Apply Denoise")
        self.apply_denoise_button.setObjectName("PrimaryButton")
        self.apply_denoise_button.clicked.connect(self._emit_denoise)

        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(8)
        source_row.addWidget(label)
        source_row.addWidget(source_control)
        source_row.addWidget(self.set_noise_sample_button)
        source_row.addWidget(self.noise_sample_label)
        source_row.addWidget(self.clear_noise_sample_button)
        source_row.addStretch(1)

        strength_row = QHBoxLayout()
        strength_row.setContentsMargins(0, 0, 0, 0)
        strength_row.setSpacing(8)
        strength_row.addWidget(QLabel("Strength"))
        strength_row.addWidget(self.denoise_slider)
        strength_row.addWidget(self.denoise_value_label)
        strength_row.addStretch(1)
        strength_row.addWidget(self.remove_denoise_button)
        strength_row.addWidget(self.apply_denoise_button)
        layout.addLayout(source_row)
        layout.addLayout(strength_row)
        return cleanup_bar

    def _build_analysis_bar(self) -> QFrame:
        analysis_bar = QFrame()
        analysis_bar.setObjectName("DatasetToolPanel")
        layout = QVBoxLayout(analysis_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel("SILENCE GUIDE")
        label.setObjectName("DatasetAnalysisLabel")
        self.threshold_spin = _analysis_spin(-80, -10, -40, " dB", 1)
        self.silence_spin = _analysis_spin(100, 5000, 500, " ms", 100)
        self.padding_spin = _analysis_spin(0, 1000, 120, " ms", 20)
        self.max_clip_spin = _analysis_spin(3, 30, 12, " s", 1)
        self.analyze_button = FeedbackButton("Analyze")
        self.analyze_button.setObjectName("DatasetAnalyzeButton")
        self.analyze_button.clicked.connect(self._emit_analyze)

        detection_row = QHBoxLayout()
        detection_row.setContentsMargins(0, 0, 0, 0)
        detection_row.setSpacing(7)
        detection_row.addWidget(label)
        detection_row.addWidget(QLabel("Threshold"))
        detection_row.addWidget(self.threshold_spin)
        detection_row.addWidget(QLabel("Silence"))
        detection_row.addWidget(self.silence_spin)
        detection_row.addStretch(1)

        shaping_row = QHBoxLayout()
        shaping_row.setContentsMargins(0, 0, 0, 0)
        shaping_row.setSpacing(7)
        shaping_row.addWidget(QLabel("Padding"))
        shaping_row.addWidget(self.padding_spin)
        shaping_row.addWidget(QLabel("Max Clip"))
        shaping_row.addWidget(self.max_clip_spin)
        shaping_row.addStretch(1)
        shaping_row.addWidget(self.analyze_button)
        layout.addLayout(detection_row)
        layout.addLayout(shaping_row)
        return analysis_bar

    def _build_secondary_tools(self) -> QFrame:
        self.cleanup_tool_button = FeedbackButton("Cleanup")
        self.analysis_tool_button = FeedbackButton("Detection")
        for index, button in enumerate(
            (self.cleanup_tool_button, self.analysis_tool_button)
        ):
            button.setObjectName("DatasetResultTab")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(
                lambda _checked=False, page=index: self.tool_stack.setCurrentIndex(page)
            )
        self.cleanup_tool_button.setChecked(True)

        tabs = QFrame()
        tabs.setObjectName("DatasetResultTabs")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(2, 2, 2, 2)
        tabs_layout.setSpacing(0)
        tabs_layout.addWidget(self.cleanup_tool_button)
        tabs_layout.addWidget(self.analysis_tool_button)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("AUDIO TOOLS")
        title.setObjectName("DatasetAnalysisLabel")
        header.addWidget(title)
        header.addWidget(tabs)
        header.addStretch(1)

        self.tool_stack = QStackedWidget()
        self.tool_stack.setObjectName("DatasetToolStack")
        self.tool_stack.addWidget(self.cleanup_bar)
        self.tool_stack.addWidget(self.analysis_bar)

        tools = QFrame()
        tools.setObjectName("DatasetSecondaryTools")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(10, 7, 10, 8)
        tools_layout.setSpacing(6)
        tools_layout.addLayout(header)
        tools_layout.addWidget(self.tool_stack)
        return tools

    def _build_result_area(self) -> tuple[QHBoxLayout, QHBoxLayout]:
        self.queue_tab = FeedbackButton("Queue 0")
        self.held_tab = FeedbackButton("Held 0")
        self.excluded_tab = FeedbackButton("Excluded 0")
        self.clips_tab = FeedbackButton("Clips 0")
        candidate_tabs = (
            (self.queue_tab, SEGMENT_PENDING),
            (self.held_tab, SEGMENT_HELD),
            (self.excluded_tab, SEGMENT_REJECTED),
        )
        for button, status in candidate_tabs:
            button.setObjectName("DatasetResultTab")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda _checked=False, value=status: self._show_candidate_page(value))
        self.clips_tab.setObjectName("DatasetResultTab")
        self.clips_tab.setCheckable(True)
        self.clips_tab.setAutoExclusive(True)
        self.clips_tab.clicked.connect(self._show_clips_page)
        self.queue_tab.setChecked(True)

        result_tabs = QFrame()
        result_tabs.setObjectName("DatasetResultTabs")
        tab_layout = QHBoxLayout(result_tabs)
        tab_layout.setContentsMargins(2, 2, 2, 2)
        tab_layout.setSpacing(0)
        tab_layout.addWidget(self.queue_tab)
        tab_layout.addWidget(self.held_tab)
        tab_layout.addWidget(self.excluded_tab)
        tab_layout.addWidget(self.clips_tab)
        result_header = QHBoxLayout()
        result_header.setContentsMargins(0, 0, 0, 0)
        result_header.addWidget(result_tabs)
        result_header.addStretch(1)

        self.candidate_list = _horizontal_list("DatasetSuggestionList")
        self.candidate_list.currentItemChanged.connect(self._on_candidate_selection_changed)
        self.clip_list = _horizontal_list("DatasetClipList")
        self.clip_list.itemSelectionChanged.connect(self._on_clip_selection_changed)
        self.result_stack = QStackedWidget()
        self.result_stack.setObjectName("DatasetResultStack")
        self.result_stack.addWidget(self.candidate_list)
        self.result_stack.addWidget(self.clip_list)
        self.result_stack.setFixedHeight(54)

        self.action_stack = QStackedWidget()
        self.action_stack.setObjectName("DatasetActionStack")
        self.action_stack.addWidget(self._build_candidate_actions())
        self.action_stack.addWidget(self._build_clip_actions())
        self.action_stack.setCurrentIndex(1)
        self.action_stack.setFixedHeight(32)

        result_row = QHBoxLayout()
        result_row.setContentsMargins(0, 0, 0, 0)
        result_row.setSpacing(10)
        result_row.addWidget(self.result_stack, 1)
        return result_header, result_row

    def _build_candidate_actions(self) -> QWidget:
        page = QWidget()
        page.setObjectName("DatasetActionPage")
        self.queue_candidate_button = FeedbackButton("Queue")
        self.hold_candidate_button = FeedbackButton("Hold  H")
        self.exclude_candidate_button = FeedbackButton("Exclude  X")
        for button, status in (
            (self.queue_candidate_button, SEGMENT_PENDING),
            (self.hold_candidate_button, SEGMENT_HELD),
            (self.exclude_candidate_button, SEGMENT_REJECTED),
        ):
            button.setObjectName("DatasetEditorSecondaryButton")
            _size_review_action(button)
            button.clicked.connect(lambda _checked=False, value=status: self._set_candidate_status(value))
        set_translated_tooltip(self.hold_candidate_button, "Hold region (H)")
        set_translated_tooltip(self.exclude_candidate_button, "Exclude region (X)")
        self.use_candidate_button = FeedbackButton("Use  A")
        self.use_candidate_button.setObjectName("DatasetEditorPrimaryButton")
        _size_review_action(self.use_candidate_button)
        set_translated_tooltip(self.use_candidate_button, "Use region (A)")
        self.use_candidate_button.clicked.connect(self._emit_use_candidate)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.queue_candidate_button)
        layout.addWidget(self.hold_candidate_button)
        layout.addWidget(self.exclude_candidate_button)
        layout.addWidget(self.use_candidate_button)
        return page

    def _build_clip_actions(self) -> QWidget:
        page = QWidget()
        page.setObjectName("DatasetActionPage")
        self.remove_clip_button = _icon_button("trash", "Remove selected clip")
        self.remove_clip_button.clicked.connect(self._remove_selected_clip)
        self.undo_button = _icon_button("undo", "Undo edit")
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.redo_button = _icon_button("redo", "Redo edit")
        self.redo_button.clicked.connect(self.redo_requested.emit)
        self.reset_button = FeedbackButton("Reset Original")
        self.reset_button.setObjectName("DatasetEditorSecondaryButton")
        _size_review_action(self.reset_button)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.add_clip_button = FeedbackButton("Add Clip")
        self.add_clip_button.setObjectName("DatasetEditorPrimaryButton")
        _size_review_action(self.add_clip_button)
        self.add_clip_button.clicked.connect(self._emit_add_clip)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self.remove_clip_button)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.add_clip_button)
        return page

    def _install_shortcuts(self) -> None:
        bindings = (
            ("Space", self.play_button.click),
            ("A", self.use_candidate_button.click),
            ("H", self.hold_candidate_button.click),
            ("X", self.exclude_candidate_button.click),
            ("R", self.ready_button.click),
        )
        self._review_shortcuts: list[QShortcut] = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            shortcut.setEnabled(False)
            self._review_shortcuts.append(shortcut)

    def set_item(self, item: ModelDatasetItem | None) -> None:
        same_item = bool(
            item is not None
            and self._item is not None
            and item.item_id == self._item.item_id
        )
        view_state = (
            self.waveform.view_state()
            if same_item
            else ClipWaveformViewState(1, 0)
        )
        previous_candidate_id = self._selected_candidate_id() if same_item else ""
        previous_candidate_filter = self._candidate_filter
        previous_clip_id = self._selected_clip_id() if same_item else ""
        self.stop_preview()
        self._item = item
        self.clip_list.clear()
        self._clear_candidates()
        if item is None:
            set_translated_text(self.title_label, "Clip Editor")
            self.detail_label.setText("")
            set_translated_text(self.review_badge, "UNREVIEWED")
            self.waveform.set_audio(None, 0, ())
            self._selection_start_ms = 0
            self._selection_end_ms = 0
            self._preview_version = "original"
            self._noise_sample_start_ms = 0
            self._noise_sample_end_ms = 0
            self.original_source_button.setChecked(True)
            self._refresh_noise_sample()
            self._sync_action_state()
            self._sync_shortcut_state()
            return

        self.title_label.setText(item.source_name)
        self._refresh_item_detail()
        self._set_review_badge(item.review_state)
        self._selection_start_ms = 0
        self._selection_end_ms = item.duration_ms
        self._play_position_ms = 0
        self._preview_version = "denoised" if item.has_denoised_audio else "original"
        self._noise_sample_start_ms = item.denoise_sample_start_ms
        self._noise_sample_end_ms = item.denoise_sample_end_ms
        self.denoise_slider.setValue(item.denoise_strength if item.has_denoised_audio else 50)
        self.original_source_button.setChecked(self._preview_version == "original")
        self.denoised_source_button.setChecked(self._preview_version == "denoised")
        self._refresh_noise_sample()
        self.waveform.set_audio(item.active_audio_path, item.duration_ms, item.clips)
        self.waveform.set_selection(0, item.duration_ms)
        for index, clip in enumerate(item.clips, start=1):
            list_item = QListWidgetItem(
                f"Clip {index:02d}   {_format_editor_time(clip.start_ms)} - {_format_editor_time(clip.end_ms)}"
            )
            list_item.setData(Qt.ItemDataRole.UserRole, clip.clip_id)
            list_item.setToolTip(str(clip.path))
            list_item.setSizeHint(QSize(226, 40))
            self.clip_list.addItem(list_item)
        self._refresh_result_tabs()
        selection_restored = same_item and self._restore_result_selection(
            previous_candidate_id,
            previous_candidate_filter,
            previous_clip_id,
        )
        if not selection_restored:
            if any(candidate.status == SEGMENT_PENDING for candidate in item.segment_candidates):
                self._show_candidate_page(SEGMENT_PENDING)
            elif any(candidate.status == SEGMENT_HELD for candidate in item.segment_candidates):
                self._show_candidate_page(SEGMENT_HELD)
            elif item.segment_candidates and not item.clips:
                self._show_candidate_page(SEGMENT_REJECTED)
            else:
                self._show_clips_page()
        if same_item:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(view_state.zoom)
            self.zoom_slider.blockSignals(False)
            self.waveform.set_zoom(view_state.zoom)
            if selection_restored:
                self.waveform.restore_view_state(view_state)
        else:
            self.zoom_slider.setValue(1)
        self._refresh_time_labels()
        self._sync_action_state()
        self._sync_shortcut_state()

    def set_navigation_state(self, has_previous: bool, has_next: bool) -> None:
        self._has_previous = has_previous
        self._has_next = has_next
        self._sync_action_state()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.waveform.set_theme_mode(theme_mode)
        for button in self._icon_buttons():
            button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        if self._item is None:
            set_translated_text(self.title_label, "Clip Editor")
            set_translated_text(self.review_badge, "UNREVIEWED")
        else:
            self._refresh_item_detail()
            self._set_review_badge(self._item.review_state)
        self._refresh_result_tabs()
        self._populate_candidate_list()
        self._refresh_noise_sample()
        self._sync_action_state()

    def set_busy(self, is_busy: bool) -> None:
        self._is_busy = is_busy
        for widget in self._interactive_widgets():
            widget.setDisabled(is_busy)
        if not is_busy:
            self._sync_action_state()
        self._sync_shortcut_state()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_shortcut_state()

    def hideEvent(self, event) -> None:  # noqa: N802
        for shortcut in self._review_shortcuts:
            shortcut.setEnabled(False)
        super().hideEvent(event)

    def stop_preview(self) -> None:
        self._player.stop()
        self._playback_timer.stop()
        if hasattr(self, "play_button"):
            self.play_button.set_icon_name("play")
        self._play_position_ms = self._selection_start_ms
        if hasattr(self, "waveform"):
            self.waveform.set_playhead(self._play_position_ms)
            self._refresh_time_labels()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_preview()
        super().closeEvent(event)

    def _set_zoom(self, value: int) -> None:
        self.zoom_label.setText(f"{value}x")
        self.waveform.set_zoom(value)

    def _set_preview_version(self, version: str) -> None:
        if self._item is None:
            return
        if version == "denoised" and not self._item.has_denoised_audio:
            version = "original"
        self.stop_preview()
        self._preview_version = version
        self.original_source_button.setChecked(version == "original")
        self.denoised_source_button.setChecked(version == "denoised")
        self.waveform.set_audio(self._preview_audio_path(), self._item.duration_ms, self._item.clips)
        self.waveform.set_zoom(self.zoom_slider.value())
        self.waveform.set_selection(self._selection_start_ms, self._selection_end_ms)
        clip_id = self._selected_clip_id()
        if clip_id:
            self.waveform.select_clip(clip_id)
        elif self.result_stack.currentIndex() == 0:
            self._refresh_candidate_overlays()
        self.waveform.set_playhead(self._play_position_ms)
        self._sync_action_state()

    def _preview_audio_path(self) -> Path:
        if self._item is None:
            return Path()
        if self._preview_version == "denoised" and self._item.has_denoised_audio:
            return self._item.denoised_path or self._item.working_path
        return self._item.working_path

    def _refresh_denoise_strength(self, value: int) -> None:
        self.denoise_value_label.setText(f"{value}%")

    def _capture_noise_sample(self) -> None:
        if self._selection_end_ms - self._selection_start_ms < 100:
            return
        self._noise_sample_start_ms = self._selection_start_ms
        self._noise_sample_end_ms = self._selection_end_ms
        self._refresh_noise_sample()
        self._sync_action_state()

    def _clear_noise_sample(self) -> None:
        self._noise_sample_start_ms = 0
        self._noise_sample_end_ms = 0
        self._refresh_noise_sample()
        self._sync_action_state()

    def _refresh_noise_sample(self) -> None:
        has_sample = self._noise_sample_end_ms - self._noise_sample_start_ms >= 100
        self.noise_sample_label.setText(
            f"{_format_editor_time(self._noise_sample_start_ms)} - "
            f"{_format_editor_time(self._noise_sample_end_ms)}"
            if has_sample
            else tr("No sample")
        )
        self.clear_noise_sample_button.setVisible(has_sample)

    def _emit_denoise(self) -> None:
        if self._item is not None:
            self.denoise_requested.emit(
                self.denoise_slider.value(),
                self._noise_sample_start_ms,
                self._noise_sample_end_ms,
            )

    def _refresh_item_detail(self) -> None:
        if self._item is None:
            self.detail_label.setText("")
            return
        mode_text = (
            tr("{count} clips", count=len(self._item.clips))
            if self._item.training_mode == TRAINING_MODE_CLIPS
            else tr("Full audio")
        )
        parts = [_format_editor_time(self._item.duration_ms), mode_text]
        if self._item.has_denoised_audio:
            parts.append(tr("Denoised {strength}%", strength=self._item.denoise_strength))
        self.detail_label.setText("  /  ".join(parts))

    def _on_selection_changed(self, start_ms: int, end_ms: int) -> None:
        self._set_selection_state(start_ms, end_ms, start_ms)

    def _on_clip_preview_changed(self, start_ms: int, end_ms: int) -> None:
        self._selection_start_ms = start_ms
        self._selection_end_ms = end_ms
        self._play_position_ms = max(start_ms, min(self._play_position_ms, end_ms))
        self._refresh_time_labels()
        self._sync_action_state()

    def _on_clip_edit_finished(self, clip_id: str, start_ms: int, end_ms: int) -> None:
        self.stop_preview()
        self.update_clip_requested.emit(clip_id, start_ms, end_ms)

    def _on_waveform_clip_selected(self, clip_id: str) -> None:
        self.clip_list.blockSignals(True)
        self.clip_list.clearSelection()
        if clip_id:
            for index in range(self.clip_list.count()):
                item = self.clip_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == clip_id:
                    self.clip_list.setCurrentItem(item)
                    item.setSelected(True)
                    break
        self.clip_list.blockSignals(False)
        if clip_id:
            self._show_clips_page()
            self._on_clip_selection_changed()
        else:
            self._sync_action_state()

    def _on_clip_selection_changed(self) -> None:
        clip_id = self._selected_clip_id()
        if not clip_id:
            self.waveform.clear_clip_selection()
            self._sync_action_state()
            return
        clip_range = self.waveform.select_clip(clip_id)
        if clip_range is not None:
            self._set_selection_state(clip_range[0], clip_range[1], clip_range[0])

    def _on_candidate_selection_changed(self, current: QListWidgetItem | None) -> None:
        candidate_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        candidate = self._candidate_by_id(candidate_id if isinstance(candidate_id, str) else "")
        self._refresh_candidate_overlays()
        if candidate is None:
            self._sync_action_state()
            return
        self.clip_list.clearSelection()
        self.waveform.clear_clip_selection()
        self.waveform.set_selection(candidate.start_ms, candidate.end_ms)
        self._set_selection_state(candidate.start_ms, candidate.end_ms, candidate.start_ms)

    def _toggle_playback(self) -> None:
        if self._item is None:
            return
        if self._player.is_playing():
            self._play_position_ms = self._player.position_ms()
            self._player.pause()
            self._playback_timer.stop()
            self.play_button.set_icon_name("play")
            return
        self._start_playback()

    def _start_playback(self) -> None:
        if self._item is None:
            return
        try:
            preview_path = prepare_preview_audio(self._preview_audio_path())
            if not (self._selection_start_ms <= self._play_position_ms < self._selection_end_ms):
                self._play_position_ms = self._selection_start_ms
            self.playback_started.emit()
            self._player.play([preview_path], start_ms=self._play_position_ms)
        except Exception as exc:
            self.stop_preview()
            self.playback_failed.emit(str(exc))
            return
        self.play_button.set_icon_name("pause")
        self._playback_timer.start()

    def _sync_playback(self) -> None:
        self._play_position_ms = self._player.position_ms()
        if self._play_position_ms >= self._selection_end_ms:
            if self.loop_button.isChecked():
                self._player.stop()
                self._play_position_ms = self._selection_start_ms
                self._start_playback()
            else:
                self.stop_preview()
            return
        if not self._player.is_playing():
            self.stop_preview()
            return
        self.waveform.set_playhead(self._play_position_ms)
        self._refresh_time_labels()
        self._sync_action_state()

    def _seek(self, position_ms: int) -> None:
        self._play_position_ms = position_ms
        self.waveform.set_playhead(position_ms)
        self._refresh_time_labels()
        self._sync_action_state()
        if self._player.is_playing():
            self._player.stop()
            self._start_playback()

    def _emit_add_clip(self) -> None:
        if self._selection_end_ms - self._selection_start_ms >= 100:
            self.add_clip_requested.emit(self._selection_start_ms, self._selection_end_ms)

    def _emit_split_clip(self) -> None:
        clip_id = self._selected_clip_id()
        if clip_id:
            self.split_clip_requested.emit(clip_id, self._play_position_ms)

    def _emit_analyze(self) -> None:
        if self._item is not None:
            self.analyze_requested.emit(
                self.threshold_spin.value(),
                self.silence_spin.value(),
                self.padding_spin.value(),
                self.max_clip_spin.value(),
            )

    def _emit_use_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            return
        if self._selection_end_ms - self._selection_start_ms >= 100:
            self.use_candidate_requested.emit(
                candidate.candidate_id,
                self._selection_start_ms,
                self._selection_end_ms,
            )

    def _set_candidate_status(self, status: str) -> None:
        candidate = self._selected_candidate()
        if candidate is not None and candidate.status != status:
            self.candidate_status_requested.emit(candidate.candidate_id, status)

    def _remove_selected_clip(self) -> None:
        clip_id = self._selected_clip_id()
        if clip_id:
            self.remove_clip_requested.emit(clip_id)

    def _show_candidate_page(self, status: str) -> None:
        self._candidate_filter = status
        self.result_stack.setCurrentIndex(0)
        self.action_stack.setCurrentIndex(0)
        self.queue_tab.setChecked(status == SEGMENT_PENDING)
        self.held_tab.setChecked(status == SEGMENT_HELD)
        self.excluded_tab.setChecked(status == SEGMENT_REJECTED)
        self.clips_tab.setChecked(False)
        self.clip_list.clearSelection()
        self.waveform.clear_clip_selection()
        self._populate_candidate_list()
        self._sync_action_state()

    def _show_clips_page(self, _checked: bool = False) -> None:
        self.result_stack.setCurrentIndex(1)
        self.action_stack.setCurrentIndex(1)
        self.queue_tab.setChecked(False)
        self.held_tab.setChecked(False)
        self.excluded_tab.setChecked(False)
        self.clips_tab.setChecked(True)
        self.candidate_list.clearSelection()
        self.waveform.set_suggestions(())
        self._sync_action_state()

    def _restore_result_selection(
        self,
        candidate_id: str,
        candidate_filter: str,
        clip_id: str,
    ) -> bool:
        candidate = self._candidate_by_id(candidate_id)
        if candidate is not None and candidate.status == candidate_filter:
            self._show_candidate_page(candidate_filter)
            for index in range(self.candidate_list.count()):
                item = self.candidate_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == candidate_id:
                    self.candidate_list.setCurrentRow(index)
                    return True
        if self._item is not None and any(
            clip.clip_id == clip_id for clip in self._item.clips
        ):
            self._show_clips_page()
            for index in range(self.clip_list.count()):
                item = self.clip_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == clip_id:
                    self.clip_list.setCurrentRow(index)
                    return True
        return False

    def _populate_candidate_list(self) -> None:
        candidates = self._filtered_candidates()
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for index, candidate in enumerate(candidates, start=1):
            item = QListWidgetItem(
                f"{index:02d}   {_format_editor_time(candidate.start_ms)} - "
                f"{_format_editor_time(candidate.end_ms)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            item.setSizeHint(QSize(218, 40))
            self.candidate_list.addItem(item)
        self.candidate_list.blockSignals(False)
        if candidates:
            self.candidate_list.setCurrentRow(0)
        else:
            self.waveform.set_suggestions(())

    def _refresh_candidate_overlays(self) -> None:
        current_id = self._selected_candidate_id()
        self.waveform.set_suggestions(
            tuple(
                (SpeechRegion(candidate.start_ms, candidate.end_ms), candidate.candidate_id == current_id)
                for candidate in self._filtered_candidates()
            )
        )

    def _clear_candidates(self) -> None:
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        self.candidate_list.blockSignals(False)
        self._refresh_result_tabs()
        if hasattr(self, "waveform"):
            self.waveform.set_suggestions(())

    def _refresh_result_tabs(self) -> None:
        candidates = self._item.segment_candidates if self._item is not None else ()
        counts = {
            status: sum(candidate.status == status for candidate in candidates)
            for status in (SEGMENT_PENDING, SEGMENT_HELD, SEGMENT_REJECTED)
        }
        set_translated_text(self.queue_tab, "Queue {count}", count=counts[SEGMENT_PENDING])
        set_translated_text(self.held_tab, "Held {count}", count=counts[SEGMENT_HELD])
        set_translated_text(self.excluded_tab, "Excluded {count}", count=counts[SEGMENT_REJECTED])
        set_translated_text(self.clips_tab, "Clips {count}", count=len(self._item.clips) if self._item else 0)

    def _filtered_candidates(self) -> tuple[SegmentCandidate, ...]:
        if self._item is None:
            return ()
        return tuple(
            candidate for candidate in self._item.segment_candidates if candidate.status == self._candidate_filter
        )

    def _selected_candidate_id(self) -> str:
        current = self.candidate_list.currentItem()
        candidate_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        return candidate_id if isinstance(candidate_id, str) else ""

    def _selected_candidate(self) -> SegmentCandidate | None:
        return self._candidate_by_id(self._selected_candidate_id())

    def _candidate_by_id(self, candidate_id: str) -> SegmentCandidate | None:
        if self._item is None or not candidate_id:
            return None
        return next(
            (candidate for candidate in self._item.segment_candidates if candidate.candidate_id == candidate_id),
            None,
        )

    def _selected_clip_id(self) -> str:
        current = self.clip_list.currentItem()
        clip_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        return clip_id if isinstance(clip_id, str) else ""

    def _selected_clip(self) -> ModelDatasetClip | None:
        clip_id = self._selected_clip_id()
        if self._item is None or not clip_id:
            return None
        return next((clip for clip in self._item.clips if clip.clip_id == clip_id), None)

    def _set_selection_state(self, start_ms: int, end_ms: int, play_position_ms: int) -> None:
        self._selection_start_ms = start_ms
        self._selection_end_ms = end_ms
        self._play_position_ms = play_position_ms
        self.waveform.set_playhead(play_position_ms)
        self._refresh_time_labels()
        self._sync_action_state()

    def _set_review_badge(self, review_state: str) -> None:
        text = {
            REVIEW_UNREVIEWED: "UNREVIEWED",
            REVIEW_EDITING: "EDITING",
            REVIEW_READY: "READY",
        }.get(review_state, "UNREVIEWED")
        set_translated_text(self.review_badge, text)
        self.review_badge.setProperty("state", review_state)
        self.review_badge.style().unpolish(self.review_badge)
        self.review_badge.style().polish(self.review_badge)

    def _sync_action_state(self) -> None:
        available = self._item is not None and not self._is_busy
        selected_clip = self._selected_clip()
        has_selection = self._selection_end_ms - self._selection_start_ms >= 100
        can_split = bool(
            selected_clip
            and self._play_position_ms - selected_clip.start_ms >= 100
            and selected_clip.end_ms - self._play_position_ms >= 100
        )
        self.play_button.setEnabled(available and has_selection)
        self.loop_button.setEnabled(available and has_selection)
        self.split_button.setEnabled(available and can_split)
        self.analyze_button.setEnabled(available)
        has_denoised = bool(self._item and self._item.has_denoised_audio)
        self.original_source_button.setEnabled(available)
        self.denoised_source_button.setEnabled(available and has_denoised)
        self.denoise_slider.setEnabled(available)
        self.set_noise_sample_button.setEnabled(available and has_selection)
        has_noise_sample = self._noise_sample_end_ms - self._noise_sample_start_ms >= 100
        self.clear_noise_sample_button.setEnabled(available and has_noise_sample)
        self.apply_denoise_button.setEnabled(available)
        self.remove_denoise_button.setEnabled(available and has_denoised)
        set_translated_text(
            self.apply_denoise_button,
            "Update Denoise" if has_denoised else "Apply Denoise",
        )
        self.add_clip_button.setEnabled(available and has_selection and selected_clip is None)
        selected_candidate = self._selected_candidate()
        has_candidate = available and selected_candidate is not None
        self.use_candidate_button.setEnabled(has_candidate)
        self.queue_candidate_button.setEnabled(has_candidate and selected_candidate.status != SEGMENT_PENDING)
        self.hold_candidate_button.setEnabled(has_candidate and selected_candidate.status != SEGMENT_HELD)
        self.exclude_candidate_button.setEnabled(has_candidate and selected_candidate.status != SEGMENT_REJECTED)
        self.remove_clip_button.setEnabled(available and selected_clip is not None)
        self.undo_button.setEnabled(available and bool(self._item and self._item.can_undo))
        self.redo_button.setEnabled(available and bool(self._item and self._item.can_redo))
        self.reset_button.setEnabled(available)
        has_training_audio = bool(self._item and self._item.training_paths)
        is_ready = bool(self._item and self._item.review_state == REVIEW_READY)
        set_translated_text(
            self.ready_button,
            "Done  R" if is_ready else "Finish  R",
        )
        has_open_segments = bool(self._item and self._item.open_segment_count)
        self.ready_button.setEnabled(available and has_training_audio and not has_open_segments and not is_ready)
        self.previous_button.setEnabled(available and self._has_previous)
        self.next_button.setEnabled(available and self._has_next)

    def _refresh_time_labels(self) -> None:
        self.position_label.setText(_format_editor_time(self._play_position_ms))
        duration = max(0, self._selection_end_ms - self._selection_start_ms)
        self.selection_label.setText(
            f"{_format_editor_time(self._selection_start_ms)}  -  {_format_editor_time(self._selection_end_ms)}"
            f"   /   {_format_editor_time(duration)}"
        )

    def _sync_shortcut_state(self) -> None:
        enabled = self.isVisible() and self._item is not None and not self._is_busy
        for shortcut in self._review_shortcuts:
            shortcut.setEnabled(enabled)

    def _icon_buttons(self) -> tuple[SvgIconButton, ...]:
        return (
            self.play_button,
            self.loop_button,
            self.split_button,
            self.previous_button,
            self.next_button,
            self.remove_clip_button,
            self.undo_button,
            self.redo_button,
            self.close_button,
            self.clear_noise_sample_button,
        )

    def _interactive_widgets(self) -> tuple[QWidget, ...]:
        return (
            *self._icon_buttons(),
            self.zoom_slider,
            self.threshold_spin,
            self.silence_spin,
            self.padding_spin,
            self.max_clip_spin,
            self.original_source_button,
            self.denoised_source_button,
            self.denoise_slider,
            self.set_noise_sample_button,
            self.noise_sample_label,
            self.remove_denoise_button,
            self.apply_denoise_button,
            self.analyze_button,
            self.cleanup_tool_button,
            self.analysis_tool_button,
            self.ready_button,
            self.queue_tab,
            self.held_tab,
            self.excluded_tab,
            self.clips_tab,
            self.candidate_list,
            self.clip_list,
            self.reset_button,
            self.add_clip_button,
            self.queue_candidate_button,
            self.hold_candidate_button,
            self.exclude_candidate_button,
            self.use_candidate_button,
        )


def _horizontal_list(object_name: str) -> QListWidget:
    list_widget = QListWidget()
    list_widget.setObjectName(object_name)
    list_widget.setFlow(QListWidget.Flow.LeftToRight)
    list_widget.setWrapping(False)
    list_widget.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
    list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    list_widget.setFixedHeight(54)
    return list_widget


def _icon_button(
    icon: str,
    tooltip: str,
    size: int = _REVIEW_CONTROL_SIZE,
) -> SvgIconButton:
    button = SvgIconButton(icon, size=size)
    button.setObjectName("DatasetEditorIconButton")
    set_translated_tooltip(button, tooltip)
    return button


def _size_review_action(button: FeedbackButton) -> None:
    button.setFixedHeight(_REVIEW_CONTROL_SIZE)
    button.setMinimumWidth(_REVIEW_ACTION_MIN_WIDTH)


def _analysis_spin(minimum: int, maximum: int, value: int, suffix: str, step: int) -> ScrollSafeSpinBox:
    spin = ScrollSafeSpinBox()
    spin.setObjectName("DatasetAnalysisSpin")
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setSingleStep(step)
    spin.setFixedWidth(108)
    return spin


def _format_editor_time(milliseconds: int) -> str:
    total_tenths = max(0, milliseconds) // 100
    minutes, tenths = divmod(total_tenths, 600)
    seconds, tenth = divmod(tenths, 10)
    return f"{minutes:02d}:{seconds:02d}.{tenth}"
