from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.clip_waveform_view import ClipWaveformView
from jang_app.qt_app.result_transport_bar import ResultTransportBar
from jang_app.qt_app.timeline_range_clip import TimelineRangeLane
from jang_app.qt_app.vocal_cleanup_result_pool import VocalCleanupResultPool
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.services.audio_metadata import format_duration, read_audio_metadata
from jang_app.services.i18n import tr
from jang_app.services.separation_assets import separation_asset_status
from jang_app.services.separation_recipe import EFFECT_REMOVAL_RECIPE
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_DEECHO_MODEL,
    VOCAL_CLEANUP_EFFECT_DEECHO,
    VOCAL_CLEANUP_EFFECT_DENOISE,
    VOCAL_CLEANUP_EFFECT_DEREVERB,
    VOCAL_CLEANUP_EFFECTS,
    VocalCleanupProject,
    VocalCleanupResult,
)
from jang_app.services.vocal_split import VocalReferenceRegion


PLAYBACK_ORIGINAL = "original"
PLAYBACK_PROCESSED = "processed"
PLAYBACK_REMOVED = "removed"


class VocalCleanupWorkspace(QWidget):
    source_changed = Signal(object)
    preview_requested = Signal(object, int, int, str, str)
    commit_preview_requested = Signal()
    cancel_preview_requested = Signal()
    region_remove_requested = Signal(str)
    render_requested = Signal()
    result_selected = Signal(object)
    result_remove_requested = Signal(object)
    playback_source_changed = Signal()
    preview_invalidated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocalCleanupWorkspace")
        self._project: VocalCleanupProject | None = None
        self._duration_ms = 0
        self._selection = (0, 0)
        self._preview_paths: dict[str, Path | None] = {
            PLAYBACK_ORIGINAL: None,
            PLAYBACK_PROCESSED: None,
            PLAYBACK_REMOVED: None,
        }
        self._playback_mode = PLAYBACK_ORIGINAL
        self._selected_effect = VOCAL_CLEANUP_EFFECT_DEREVERB
        self._theme_mode = "white"

        self.source_panel = self._build_source_panel()
        self.timeline_panel = self._build_timeline_panel()
        self.inspector_panel = self._build_inspector_panel()
        self.splitter = create_workspace_splitter(
            (self.source_panel, self.timeline_panel, self.inspector_panel),
            object_name="VocalCleanupWorkspaceSplitter",
            sizes=(300, 900, 320),
            stretch_factors=(0, 1, 0),
            collapsible=(True, False, True),
        )
        self.transport_bar = ResultTransportBar()
        self.render_bar = _CleanupRenderBar()
        self.render_bar.triggered.connect(self.render_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.render_bar, 0)
        layout.addWidget(self.transport_bar, 0)
        self.apply_language()
        self._sync_state()

    def _build_source_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.source_title = QLabel()
        self.source_title.setObjectName("SectionTitle")
        self.source_pool = VocalVersionPool("vocal", title_key="Vocal Source")
        self.source_pool.selection_changed.connect(self._on_source_changed)
        self.result_pool = VocalCleanupResultPool()
        self.result_pool.result_changed.connect(self._on_result_selected)
        self.result_pool.remove_requested.connect(self.result_remove_requested.emit)
        layout.addWidget(self.source_title)
        layout.addWidget(self.source_pool, 1)
        layout.addWidget(self.result_pool, 1)
        return panel

    def _build_timeline_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.timeline_title = QLabel()
        self.timeline_title.setObjectName("SectionTitle")
        self.selection_label = QLabel()
        self.selection_label.setObjectName("MutedText")
        header.addWidget(self.timeline_title, 1)
        header.addWidget(self.selection_label, 0)
        self.waveform = ClipWaveformView(panel)
        self.waveform.setObjectName("VocalCleanupWaveform")
        self.waveform.setMinimumHeight(260)
        self.waveform.selection_changed.connect(self._on_selection_changed)
        self.waveform.seek_requested.connect(self._on_seek_requested)
        self.region_lane_label = QLabel()
        self.region_lane_label.setObjectName("CardTitle")
        self.region_lane = TimelineRangeLane()
        self.region_lane.region_activated.connect(self._on_region_activated)
        self.region_lane.region_remove_requested.connect(
            self.region_remove_requested.emit
        )
        self.region_lane.seek_requested.connect(self._on_seek_requested)
        self.empty_hint = QLabel()
        self.empty_hint.setObjectName("MutedText")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        layout.addLayout(header)
        layout.addWidget(self._build_tool_selector(), 0)
        layout.addWidget(self.waveform, 1)
        layout.addWidget(self.empty_hint, 0)
        layout.addWidget(self.region_lane_label)
        layout.addWidget(self.region_lane, 0)
        layout.addWidget(self._build_compare_control(), 0)
        return panel

    def _build_tool_selector(self) -> QFrame:
        selector = QFrame()
        selector.setObjectName("InsetCard")
        layout = QHBoxLayout(selector)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        self.tool_selector_title = QLabel()
        self.tool_selector_title.setObjectName("CardTitle")
        control = QFrame()
        control.setObjectName("SegmentedControl")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict[str, FeedbackButton] = {}
        for index, effect in enumerate(VOCAL_CLEANUP_EFFECTS):
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(effect == self._selected_effect)
            self.tool_group.addButton(button, index)
            self.tool_buttons[effect] = button
            control_layout.addWidget(button, 1)
        self.tool_group.idClicked.connect(self._on_tool_changed)
        layout.addWidget(self.tool_selector_title, 0)
        layout.addWidget(control, 1)
        return selector

    def _build_compare_control(self) -> QFrame:
        control = QFrame()
        control.setObjectName("SegmentedControl")
        layout = QHBoxLayout(control)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.playback_group = QButtonGroup(self)
        self.playback_group.setExclusive(True)
        self.playback_buttons: dict[str, FeedbackButton] = {}
        for index, mode in enumerate(
            (PLAYBACK_ORIGINAL, PLAYBACK_PROCESSED, PLAYBACK_REMOVED)
        ):
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.playback_group.addButton(button, index)
            self.playback_buttons[mode] = button
            layout.addWidget(button, 1)
        self.playback_group.idClicked.connect(self._on_playback_mode_changed)
        return control

    def _build_inspector_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        self.inspector_title = QLabel()
        self.inspector_title.setObjectName("SectionTitle")
        self.tool_detail_stack = QStackedWidget()
        self.tool_detail_stack.setObjectName("VocalCleanupToolDetails")
        self.tool_detail_titles: dict[str, QLabel] = {}
        self.tool_detail_descriptions: dict[str, QLabel] = {}
        self.tool_detail_statuses: dict[str, QLabel] = {}
        for effect in VOCAL_CLEANUP_EFFECTS:
            self.tool_detail_stack.addWidget(self._build_tool_detail_page(effect))

        self.strength_title = QLabel()
        self.strength_title.setObjectName("CardTitle")
        strength_control = QFrame()
        strength_control.setObjectName("SegmentedControl")
        strength_layout = QHBoxLayout(strength_control)
        strength_layout.setContentsMargins(4, 4, 4, 4)
        strength_layout.setSpacing(4)
        self.strength_group = QButtonGroup(self)
        self.strength_group.setExclusive(True)
        self.strength_buttons: dict[str, FeedbackButton] = {}
        for index, strength in enumerate(("conservative", "standard", "strong")):
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(strength == "standard")
            self.strength_group.addButton(button, index)
            self.strength_buttons[strength] = button
            strength_layout.addWidget(button, 1)
        self.strength_group.idClicked.connect(self._on_tool_settings_changed)

        self.preview_action = _CleanupInlineAction()
        self.preview_action.triggered.connect(self._request_preview)
        self.preview_action.cancelled.connect(self.cancel_preview_requested.emit)
        self.preview_action.commit_requested.connect(
            self.commit_preview_requested.emit
        )
        layout.addWidget(self.inspector_title)
        layout.addWidget(self.tool_detail_stack)
        layout.addWidget(self.strength_title)
        layout.addWidget(strength_control)
        layout.addWidget(self.preview_action)
        layout.addStretch(1)
        return panel

    def _build_tool_detail_page(self, effect: str) -> QFrame:
        page = QFrame()
        page.setObjectName("InsetCard")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title = QLabel()
        title.setObjectName("CardTitle")
        description = QLabel()
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        status = QLabel()
        status.setObjectName("StatusChip")
        self.tool_detail_titles[effect] = title
        self.tool_detail_descriptions[effect] = description
        self.tool_detail_statuses[effect] = status
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(status)
        return page

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
    ) -> SongVocalVersion | None:
        return self.source_pool.set_versions(versions, selected_job_dir)

    def selected_version(self) -> SongVocalVersion | None:
        return self.source_pool.selected_version()

    def set_project(
        self,
        project: VocalCleanupProject | None,
        *,
        selected_result_id: str = "",
    ) -> None:
        self._project = project
        source = project.source_path if project is not None else None
        self._duration_ms = 0
        if source is not None:
            try:
                self._duration_ms = read_audio_metadata(source).duration_ms
            except Exception:
                self._duration_ms = 0
        self.waveform.set_audio(source, self._duration_ms, ())
        self.waveform.set_selection(0, 0)
        self._selection = (0, 0)
        regions = project.regions if project is not None else ()
        self.region_lane.set_duration_ms(self._duration_ms)
        self.region_lane.set_regions(
            tuple(
                VocalReferenceRegion(region.region_id, region.start_ms, region.end_ms)
                for region in regions
            )
        )
        selected = self.result_pool.set_results(
            project.results if project is not None else (),
            selected_result_id,
        )
        self._preview_paths = {
            PLAYBACK_ORIGINAL: source,
            PLAYBACK_PROCESSED: selected.path if selected is not None else None,
            PLAYBACK_REMOVED: None,
        }
        self.preview_action.set_preview_available(False)
        self.preview_action.set_progress(0)
        self._set_playback_mode(
            PLAYBACK_PROCESSED if selected is not None else PLAYBACK_ORIGINAL,
            notify=False,
        )
        self._sync_state()

    def set_preview_paths(self, processed: Path, removed: Path) -> None:
        self._preview_paths[PLAYBACK_PROCESSED] = processed
        self._preview_paths[PLAYBACK_REMOVED] = removed
        self._set_playback_mode(PLAYBACK_PROCESSED)
        self.preview_action.set_preview_available(True)
        self._sync_state()

    def clear_pending_preview(self) -> None:
        self._preview_paths[PLAYBACK_REMOVED] = None
        result = self.result_pool.selected_result()
        self._preview_paths[PLAYBACK_PROCESSED] = result.path if result is not None else None
        self.preview_action.set_preview_available(False)
        self.preview_action.set_progress(0)
        if (
            self._playback_mode in {PLAYBACK_PROCESSED, PLAYBACK_REMOVED}
            and self._preview_paths.get(self._playback_mode) is None
        ):
            self._set_playback_mode(PLAYBACK_ORIGINAL)
        self._sync_state()

    def playback_tracks(self) -> tuple[tuple[Path, float], ...]:
        path = self._preview_paths.get(self._playback_mode)
        return ((path, 1.0),) if path is not None and path.is_file() else ()

    def set_playhead_ms(self, position_ms: int) -> None:
        self.waveform.set_playhead(position_ms)

    def set_preview_running(self, running: bool) -> None:
        self.preview_action.set_running(running)

    def set_preview_progress(self, value: int) -> None:
        self.preview_action.set_progress(value)

    def set_preview_status(self, text: str) -> None:
        self.preview_action.set_status(text)

    def set_render_running(self, running: bool) -> None:
        self.render_bar.set_running(running)

    def set_render_progress(self, value: int) -> None:
        self.render_bar.set_progress(value)

    def set_render_status(self, text: str) -> None:
        self.render_bar.set_status(text)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.source_pool.set_theme_mode(theme_mode)
        self.result_pool.set_theme_mode(theme_mode)
        self.waveform.set_theme_mode(theme_mode)
        self.region_lane.set_theme_mode(theme_mode)
        self.transport_bar.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.source_title.setText(tr("Vocal Cleanup"))
        self.timeline_title.setText(tr("Cleanup Timeline"))
        self.tool_selector_title.setText(tr("Cleanup Tool"))
        self.region_lane_label.setText(tr("Cleanup Regions"))
        self.empty_hint.setText(tr("Drag across the waveform to select a range to clean."))
        self.inspector_title.setText(tr("Tool Details"))
        for effect, label in (
            (VOCAL_CLEANUP_EFFECT_DEREVERB, "Dereverb"),
            (VOCAL_CLEANUP_EFFECT_DEECHO, "De-echo"),
            (VOCAL_CLEANUP_EFFECT_DENOISE, "Noise Removal"),
        ):
            self.tool_buttons[effect].setText(tr(label))
            self.tool_detail_titles[effect].setText(tr(label))
        self.tool_detail_descriptions[VOCAL_CLEANUP_EFFECT_DEREVERB].setText(
            tr("Reduces room reverb only in the selected vocal range while protecting quiet phrases.")
        )
        self.tool_detail_descriptions[VOCAL_CLEANUP_EFFECT_DEECHO].setText(
            tr("Reduces repeated and delayed vocal echoes in the selected range.")
        )
        self.tool_detail_descriptions[VOCAL_CLEANUP_EFFECT_DENOISE].setText(
            tr("Reduces steady microphone and background noise in the selected vocal range.")
        )
        status = separation_asset_status(EFFECT_REMOVAL_RECIPE.effect_model)
        self.tool_detail_statuses[VOCAL_CLEANUP_EFFECT_DEREVERB].setText(
            tr(status.status_text)
        )
        deecho_status = separation_asset_status(VOCAL_CLEANUP_DEECHO_MODEL)
        self.tool_detail_statuses[VOCAL_CLEANUP_EFFECT_DEECHO].setText(
            tr(deecho_status.status_text)
        )
        self.tool_detail_statuses[VOCAL_CLEANUP_EFFECT_DENOISE].setText(
            tr("Built-in processing")
        )
        self.strength_title.setText(tr("Strength"))
        for key, label in (
            ("conservative", "Conservative"),
            ("standard", "Standard"),
            ("strong", "Strong"),
        ):
            self.strength_buttons[key].setText(tr(label))
        for key, label in (
            (PLAYBACK_ORIGINAL, "Original"),
            (PLAYBACK_PROCESSED, "Processed"),
            (PLAYBACK_REMOVED, "Removed Sound"),
        ):
            self.playback_buttons[key].setText(tr(label))
        self.preview_action.apply_language()
        self.render_bar.apply_language()
        self.source_pool.apply_language()
        self.result_pool.apply_language()
        self.transport_bar.apply_language()
        self._update_selection_label()

    def _on_source_changed(self, version: SongVocalVersion) -> None:
        self.source_changed.emit(version)

    def _on_selection_changed(self, start_ms: int, end_ms: int) -> None:
        self._selection = (start_ms, end_ms)
        self.preview_invalidated.emit()
        self.clear_pending_preview()
        self._update_selection_label()
        self._sync_state()

    def _on_tool_changed(self, index: int) -> None:
        effect = VOCAL_CLEANUP_EFFECTS[max(0, min(index, len(VOCAL_CLEANUP_EFFECTS) - 1))]
        if effect == self._selected_effect:
            return
        self._selected_effect = effect
        self.tool_detail_stack.setCurrentIndex(VOCAL_CLEANUP_EFFECTS.index(effect))
        self._on_tool_settings_changed()

    def _on_tool_settings_changed(self, *_args) -> None:
        had_preview = self.preview_action.preview_available()
        self.preview_invalidated.emit()
        self.clear_pending_preview()
        if had_preview:
            self.set_preview_status("Settings changed. Create a new preview.")

    def _on_seek_requested(self, position_ms: int) -> None:
        self.transport_bar.seek_requested.emit(position_ms)

    def _on_region_activated(self, region_id: str) -> None:
        region = self._project.region(region_id) if self._project is not None else None
        if region is None:
            return
        self.waveform.set_selection(region.start_ms, region.end_ms)
        self._selection = (region.start_ms, region.end_ms)
        self._update_selection_label()

    def _on_result_selected(self, result: VocalCleanupResult) -> None:
        self._preview_paths[PLAYBACK_PROCESSED] = result.path
        self._set_playback_mode(PLAYBACK_PROCESSED)
        self.result_selected.emit(result)

    def _on_playback_mode_changed(self, index: int) -> None:
        mode = (PLAYBACK_ORIGINAL, PLAYBACK_PROCESSED, PLAYBACK_REMOVED)[index]
        self._set_playback_mode(mode)

    def _set_playback_mode(self, mode: str, *, notify: bool = True) -> None:
        path = self._preview_paths.get(mode)
        if path is None or not path.is_file():
            mode = PLAYBACK_ORIGINAL
        self._playback_mode = mode
        self.playback_buttons[mode].setChecked(True)
        self._sync_compare_buttons()
        if notify:
            self.playback_source_changed.emit()

    def _request_preview(self) -> None:
        version = self.selected_version()
        if version is None:
            return
        start_ms, end_ms = self._selection
        self.preview_requested.emit(
            version,
            start_ms,
            end_ms,
            self._selected_effect,
            self._selected_strength(),
        )

    def _selected_strength(self) -> str:
        index = self.strength_group.checkedId()
        return ("conservative", "standard", "strong")[max(0, index)]

    def _sync_state(self) -> None:
        has_source = self._project is not None and self._duration_ms > 0
        has_selection = self._selection[1] - self._selection[0] >= 250
        self.preview_action.set_action_enabled(has_source and has_selection)
        region_count = len(self._project.regions) if self._project is not None else 0
        self.render_bar.set_region_count(region_count)
        self.render_bar.set_action_enabled(region_count > 0)
        self.empty_hint.setVisible(not has_selection)
        self._sync_compare_buttons()

    def _sync_compare_buttons(self) -> None:
        for mode, button in self.playback_buttons.items():
            path = self._preview_paths.get(mode)
            button.setEnabled(path is not None and path.is_file())

    def _update_selection_label(self) -> None:
        start_ms, end_ms = self._selection
        self.selection_label.setText(
            tr("Selected {start} - {end}").format(
                start=format_duration(start_ms),
                end=format_duration(end_ms),
            )
            if end_ms > start_ms
            else tr("No range selected")
        )


class _CleanupInlineAction(QFrame):
    triggered = Signal()
    cancelled = Signal()
    commit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("InsetCard")
        self._enabled = False
        self._running = False
        self._preview_available = False
        self._status_key = "Compare before adding this range."
        self.title = QLabel()
        self.title.setObjectName("CardTitle")
        self.status = QLabel()
        self.status.setObjectName("MutedText")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.button = FeedbackButton()
        self.button.setObjectName("PrimaryButton")
        self.button.clicked.connect(self.triggered.emit)
        self.cancel_button = FeedbackButton()
        self.cancel_button.setObjectName("SecondaryButton")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        self.commit_button = FeedbackButton()
        self.commit_button.setObjectName("PrimaryButton")
        self.commit_button.clicked.connect(self.commit_requested.emit)
        decision_actions = QHBoxLayout()
        decision_actions.setContentsMargins(0, 0, 0, 0)
        decision_actions.setSpacing(8)
        decision_actions.addWidget(self.cancel_button, 1)
        decision_actions.addWidget(self.commit_button, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(9)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.button)
        layout.addLayout(decision_actions)
        self.apply_language()
        self._sync_enabled()

    def set_action_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._sync_enabled()

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._sync_enabled()

    def set_preview_available(self, available: bool) -> None:
        self._preview_available = bool(available)
        self.apply_language()
        self._sync_enabled()

    def preview_available(self) -> bool:
        return self._preview_available

    def set_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))

    def set_status(self, text: str) -> None:
        self._status_key = text
        self.status.setText(tr(self._status_key))

    def apply_language(self) -> None:
        self.title.setText(
            tr("Preview Ready")
            if self._preview_available
            else tr("Selected Range Preview")
        )
        self.button.setText(
            tr("Try Preview Again")
            if self._preview_available
            else tr("Create Preview")
        )
        self.cancel_button.setText(tr("Cancel Preview"))
        self.commit_button.setText(tr("Apply to This Range"))
        self.status.setText(tr(self._status_key))

    def _sync_enabled(self) -> None:
        self.button.setEnabled(self._enabled and not self._running)
        self.cancel_button.setVisible(self._preview_available)
        self.commit_button.setVisible(self._preview_available)
        self.cancel_button.setEnabled(self._preview_available and not self._running)
        self.commit_button.setEnabled(self._preview_available and not self._running)
        self.progress.setVisible(self._running or self._preview_available)


class _CleanupRenderBar(QFrame):
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ResultTransportBar")
        self.setFixedHeight(58)
        self._action_enabled = False
        self._running = False
        self._region_count = 0
        self._status_key = ""
        self.label = QLabel()
        self.label.setObjectName("CardTitle")
        self.status = QLabel()
        self.status.setObjectName("MutedText")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.button = FeedbackButton()
        self.button.setObjectName("PrimaryButton")
        self.button.setMinimumWidth(140)
        self.button.clicked.connect(self.triggered.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(12)
        layout.addWidget(self.label, 0)
        layout.addWidget(self.status, 0)
        layout.addWidget(self.progress, 1)
        layout.addWidget(self.button, 0)
        self.apply_language()

    def set_region_count(self, count: int) -> None:
        self._region_count = max(0, count)
        if not self._status_key:
            self._sync_status()

    def set_action_enabled(self, enabled: bool) -> None:
        self._action_enabled = bool(enabled)
        self._sync_enabled()

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._sync_enabled()

    def set_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))

    def set_status(self, text: str) -> None:
        self._status_key = text
        self._sync_status()

    def apply_language(self) -> None:
        self.label.setText(tr("Create Clean Vocal"))
        self._sync_status()
        self.button.setText(tr("Create Clean Vocal"))

    def _sync_status(self) -> None:
        self.status.setText(
            tr(self._status_key)
            if self._status_key
            else tr("{count} cleanup regions").format(count=self._region_count)
        )

    def _sync_enabled(self) -> None:
        self.button.setEnabled(self._action_enabled and not self._running)
