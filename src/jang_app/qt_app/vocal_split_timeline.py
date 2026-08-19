from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.timeline_range_clip import TimelineRangeLane
from jang_app.qt_app.widgets import (
    FeedbackButton,
    SvgIconButton,
    WaveformView,
    attach_transparent_scroll_widget,
)
from jang_app.services.audio_metadata import format_duration, read_audio_metadata
from jang_app.services.i18n import tr
from jang_app.services.vocal_split import (
    VocalReferenceRegion,
    VocalSplitRun,
    VocalSplitStem,
)


_TRACK_HEADER_WIDTH = 184
_TRACK_HEIGHT = 96


class VocalSplitTimelinePanel(QFrame):
    """Multi-track vocal timeline with per-stem reference-range editing."""

    stem_selected = Signal(object, object)
    rename_requested = Signal(object, object)
    seek_requested = Signal(float)
    playback_settings_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocalSplitTimelinePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(560)
        self._theme_mode = "white"
        self._group: VocalSplitRun | None = None
        self._selected_path: Path | None = None
        self._muted_paths: set[Path] = set()
        self._track_rows: dict[Path, _VocalTimelineTrack] = {}
        self._playhead_ratio = 0.0
        self._reference_regions: dict[
            tuple[str, str], tuple[VocalReferenceRegion, ...]
        ] = {}
        self._selected_reference_ids: dict[tuple[str, str], str] = {}
        self._reference_mode = False
        self._backend_available = False
        self._backend_detail = "Singer separation model is not connected yet."
        self._minimum_reference_ms = 1_000
        self._maximum_reference_ms = 60_000

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("VocalTimelineCount")
        self.group_meta_label = QLabel()
        self.group_meta_label.setObjectName("VocalTimelineGroupMeta")
        self.rename_button = SvgIconButton("edit", size=30)
        self.rename_button.clicked.connect(self._request_rename)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(7)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        header.addWidget(self.group_meta_label)
        header.addWidget(self.rename_button)

        self.ruler = _VocalTimelineRuler()
        self.track_content = QWidget()
        self.track_content.setObjectName("VocalTimelineContent")
        self.track_layout = QVBoxLayout(self.track_content)
        self.track_layout.setContentsMargins(0, 0, 0, 0)
        self.track_layout.setSpacing(0)
        self.track_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("VocalTimelineEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("VocalTimelineScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        attach_transparent_scroll_widget(self.scroll, self.track_content)

        timeline = QFrame()
        timeline.setObjectName("VocalTimelineSurface")
        timeline_layout = QVBoxLayout(timeline)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(0)
        timeline_layout.addWidget(self.ruler)
        timeline_layout.addWidget(self.scroll, 1)

        self.inline_editor = QFrame(self.track_content)
        self.inline_editor.setObjectName("VocalReferenceInlineEditor")
        self.inline_editor.setFixedHeight(46)
        inline_layout = QHBoxLayout(self.inline_editor)
        inline_layout.setContentsMargins(0, 0, 0, 0)
        inline_layout.setSpacing(0)

        self.reference_toolbar = QFrame()
        self.reference_toolbar.setObjectName("VocalReferenceToolbar")
        self.reference_toolbar.setFixedWidth(_TRACK_HEADER_WIDTH)
        toolbar_layout = QHBoxLayout(self.reference_toolbar)
        toolbar_layout.setContentsMargins(12, 5, 10, 5)
        toolbar_layout.setSpacing(7)
        self.reference_mode_button = SvgIconButton("range", size=34)
        self.reference_mode_button.setObjectName("VocalReferenceModeButton")
        self.reference_mode_button.setCheckable(True)
        self.reference_mode_button.toggled.connect(self._set_reference_mode)
        self.action = _VocalSplitInlineAction("Separate selected vocal")
        toolbar_layout.addWidget(self.reference_mode_button)
        toolbar_layout.addWidget(self.action)
        toolbar_layout.addStretch(1)

        self.reference_lane = TimelineRangeLane()
        self.reference_lane.region_activated.connect(self._select_reference_region)
        self.reference_lane.region_remove_requested.connect(
            self._remove_reference_region
        )
        self.reference_lane.seek_requested.connect(self._seek_reference_position)
        inline_layout.addWidget(self.reference_toolbar)
        inline_layout.addWidget(self.reference_lane, 1)
        self.inline_editor.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(timeline, 1)

        self.apply_language()
        self.set_theme_mode(self._theme_mode)
        self.set_group(None)

    def set_group(
        self,
        group: VocalSplitRun | None,
        preferred_path: Path | None = None,
    ) -> VocalSplitStem | None:
        previous_path = self._selected_path
        available = (
            {stem.path.expanduser().resolve(): stem for stem in group.stems}
            if group is not None
            else {}
        )
        requested = preferred_path.expanduser().resolve() if preferred_path else None
        self._selected_path = (
            requested
            if requested in available
            else previous_path
            if previous_path in available
            else next(iter(available), None)
        )
        self._group = group
        self._muted_paths.intersection_update(available)
        self._rebuild_tracks()
        return self.selected_stem()

    def selected_stem(self) -> VocalSplitStem | None:
        run = self.selected_group()
        if run is None or self._selected_path is None:
            return None
        return next(
            (
                stem
                for stem in run.stems
                if stem.path.expanduser().resolve() == self._selected_path
            ),
            None,
        )

    def selected_group(self) -> VocalSplitRun | None:
        return self._group

    def reference_regions(self) -> tuple[VocalReferenceRegion, ...]:
        group = self.selected_group()
        stem = self.selected_stem()
        if group is None or stem is None:
            return ()
        return self._reference_regions.get((group.run_id, stem.stem_id), ())

    def set_backend_status(
        self,
        available: bool,
        detail: str,
        *,
        minimum_reference_ms: int = 1_000,
        maximum_reference_ms: int = 60_000,
    ) -> None:
        self._backend_available = bool(available)
        self._backend_detail = detail.strip()
        self._minimum_reference_ms = max(100, int(minimum_reference_ms))
        self._maximum_reference_ms = max(
            self._minimum_reference_ms,
            int(maximum_reference_ms),
        )
        self._sync_reference_tool()

    def refresh_backend_status(self) -> None:
        self._sync_reference_tool()

    def playback_tracks(self) -> tuple[tuple[Path, float], ...]:
        run = self.selected_group()
        if run is None:
            return ()
        return tuple(
            (stem.path, 0.0 if stem.path.expanduser().resolve() in self._muted_paths else 1.0)
            for stem in run.stems
            if stem.path.is_file()
        )

    def set_playhead_ratio(self, ratio: float) -> None:
        self._playhead_ratio = max(0.0, min(1.0, float(ratio)))
        for row in self._track_rows.values():
            row.set_playhead_ratio(self._playhead_ratio)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        tokens = theme_tokens(theme_mode)
        self.setStyleSheet(_timeline_stylesheet(tokens))
        self.ruler.set_theme_mode(theme_mode)
        self.rename_button.set_theme_mode(theme_mode)
        self.reference_mode_button.set_theme_mode(theme_mode)
        self.action.set_theme_mode(theme_mode)
        self.reference_lane.set_theme_mode(theme_mode)
        for row in self._track_rows.values():
            row.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Separated Vocals"))
        self.empty_label.setText(tr("Select a vocal group"))
        self.rename_button.setToolTip(tr("Rename"))
        self.ruler.setToolTip(tr("All unmuted vocals play together."))
        self.reference_mode_button.setToolTip(tr("Add solo range"))
        self.action.set_button_text("Separate selected vocal")
        self._rebuild_tracks()

    def refresh_layout(self) -> None:
        self.track_layout.invalidate()
        self.track_layout.activate()
        self.track_content.updateGeometry()
        self.scroll.viewport().update()

    def _rebuild_tracks(self) -> None:
        while self.track_layout.count():
            item = self.track_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                if widget not in {self.empty_label, self.inline_editor}:
                    widget.deleteLater()
        self._track_rows.clear()
        run = self.selected_group()
        stems = run.stems if run is not None else ()
        stem_paths = {stem.path.expanduser().resolve() for stem in stems}
        if self._selected_path not in stem_paths:
            self._selected_path = (
                stems[0].path.expanduser().resolve() if stems else None
            )
        self.count_label.setText(str(len(stems)))
        self.group_meta_label.setText(tr(run.method_label) if run is not None else "")
        self.group_meta_label.setToolTip(run.model if run is not None else "")
        self.ruler.set_duration_ms(_run_duration_ms(stems))

        if not stems:
            self.inline_editor.hide()
            self.empty_label.show()
            self.track_layout.addWidget(self.empty_label, 1)
        else:
            self.empty_label.hide()
            for stem in stems:
                path = stem.path.expanduser().resolve()
                row = _VocalTimelineTrack(stem)
                row.set_selected(path == self._selected_path)
                row.set_muted(path in self._muted_paths)
                row.set_playhead_ratio(self._playhead_ratio)
                row.set_theme_mode(self._theme_mode)
                row.set_reference_regions(
                    self._reference_regions.get((run.run_id, stem.stem_id), ())
                )
                row.set_reference_mode(
                    path == self._selected_path and self._reference_mode
                )
                row.activated.connect(
                    lambda selected_stem, selected_run=run: self._select_stem(
                        selected_run,
                        selected_stem,
                    )
                )
                row.muted_changed.connect(
                    lambda muted, selected_stem=stem: self._set_stem_muted(
                        selected_stem,
                        muted,
                    )
                )
                row.seek_requested.connect(self.seek_requested.emit)
                row.reference_region_created.connect(
                    lambda start_ms, end_ms, selected_run=run, selected_stem=stem: (
                        self._add_reference_region(
                            selected_run,
                            selected_stem,
                            start_ms,
                            end_ms,
                        )
                    )
                )
                row.reference_region_selected.connect(self._select_reference_region)
                row.reference_region_changed.connect(self._update_reference_region)
                self._track_rows[path] = row
                if path == self._selected_path:
                    self.track_layout.addWidget(self.inline_editor)
                    self.inline_editor.show()
                self.track_layout.addWidget(row)
            self.track_layout.addStretch(1)
        self._sync_actions()
        self._sync_reference_tool()
        self.refresh_layout()

    def _select_stem(self, run: VocalSplitRun, stem: VocalSplitStem) -> None:
        path = stem.path.expanduser().resolve()
        self._selected_path = path
        for row_path, row in self._track_rows.items():
            row.set_selected(row_path == path)
            row.set_reference_mode(row_path == path and self._reference_mode)
        self._move_inline_editor(path)
        self._sync_actions()
        self._sync_reference_tool()
        self.stem_selected.emit(run, stem)

    def _move_inline_editor(self, selected_path: Path) -> None:
        row = self._track_rows.get(selected_path)
        if row is None:
            self.inline_editor.hide()
            return
        self.track_layout.removeWidget(self.inline_editor)
        row_index = self.track_layout.indexOf(row)
        self.track_layout.insertWidget(row_index, self.inline_editor)
        self.inline_editor.show()
        self.refresh_layout()

    def _set_stem_muted(self, stem: VocalSplitStem, muted: bool) -> None:
        path = stem.path.expanduser().resolve()
        if muted:
            self._muted_paths.add(path)
        else:
            self._muted_paths.discard(path)
        self.playback_settings_changed.emit()

    def _sync_actions(self) -> None:
        has_stem = self.selected_stem() is not None
        self.rename_button.setEnabled(has_stem)

    def _set_reference_mode(self, enabled: bool) -> None:
        self._reference_mode = bool(enabled)
        selected = self.selected_stem()
        selected_path = selected.path.expanduser().resolve() if selected is not None else None
        for path, row in self._track_rows.items():
            row.set_reference_mode(path == selected_path and self._reference_mode)

    def _add_reference_region(
        self,
        group: VocalSplitRun,
        stem: VocalSplitStem,
        start_ms: int,
        end_ms: int,
    ) -> None:
        start = max(0, int(start_ms))
        end = max(0, int(end_ms))
        if end <= start:
            return
        key = (group.run_id, stem.stem_id)
        region = VocalReferenceRegion(
            f"reference-{uuid4().hex[:10]}",
            start,
            end,
        )
        regions = tuple(
            sorted(
                (*self._reference_regions.get(key, ()), region),
                key=lambda item: (item.start_ms, item.end_ms),
            )
        )
        self._reference_regions[key] = regions
        self._selected_reference_ids[key] = region.region_id
        row = self._track_rows.get(stem.path.expanduser().resolve())
        if row is not None:
            row.set_reference_regions(regions)
        self._sync_reference_tool()

    def _update_reference_region(
        self,
        region_id: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        group = self.selected_group()
        stem = self.selected_stem()
        if group is None or stem is None:
            return
        key = (group.run_id, stem.stem_id)
        regions = tuple(
            VocalReferenceRegion(region.region_id, int(start_ms), int(end_ms))
            if region.region_id == region_id
            else region
            for region in self._reference_regions.get(key, ())
        )
        self._reference_regions[key] = tuple(
            sorted(regions, key=lambda item: (item.start_ms, item.end_ms))
        )
        row = self._track_rows.get(stem.path.expanduser().resolve())
        if row is not None:
            row.set_reference_regions(self._reference_regions[key])
        self._sync_reference_tool()

    def _select_reference_region(self, region_id: str) -> None:
        group = self.selected_group()
        stem = self.selected_stem()
        if group is None or stem is None:
            return
        self._selected_reference_ids[(group.run_id, stem.stem_id)] = region_id
        self._sync_reference_tool()

    def _remove_reference_region(self, region_id: str) -> None:
        group = self.selected_group()
        stem = self.selected_stem()
        if group is None or stem is None:
            return
        key = (group.run_id, stem.stem_id)
        regions = tuple(
            region
            for region in self._reference_regions.get(key, ())
            if region.region_id != region_id
        )
        self._reference_regions[key] = regions
        self._selected_reference_ids[key] = ""
        row = self._track_rows.get(stem.path.expanduser().resolve())
        if row is not None:
            row.set_reference_regions(regions)
        self._sync_reference_tool()

    def _seek_reference_position(self, position_ms: int) -> None:
        duration_ms = _run_duration_ms(self._group.stems) if self._group is not None else 0
        if duration_ms > 0:
            self.seek_requested.emit(max(0.0, min(1.0, position_ms / duration_ms)))

    def _sync_reference_tool(self) -> None:
        stem = self.selected_stem()
        group = self.selected_group()
        key = (group.run_id, stem.stem_id) if group is not None and stem is not None else None
        regions = self.reference_regions()
        selected_region_id = (
            self._selected_reference_ids.get(key, "") if key is not None else ""
        )
        self.reference_mode_button.setEnabled(stem is not None)
        self.reference_lane.set_duration_ms(
            _stem_duration_ms(stem) if stem is not None else 0
        )
        self.reference_lane.set_regions(regions, selected_region_id)
        selected_row = (
            self._track_rows.get(stem.path.expanduser().resolve())
            if stem is not None
            else None
        )
        if selected_row is not None:
            selected_row.set_reference_regions(regions, selected_region_id)
        valid_ranges = bool(regions) and all(
            self._minimum_reference_ms <= region.duration_ms <= self._maximum_reference_ms
            for region in regions
        )
        status = tr(self._backend_detail)
        self.reference_lane.setToolTip(status)
        self.action.set_detail(status)
        self.action.set_action_enabled(
            stem is not None and valid_ranges and self._backend_available
        )

    def _request_rename(self) -> None:
        self._emit_selected(self.rename_requested)

    def _emit_selected(self, signal: Signal) -> None:
        run = self.selected_group()
        stem = self.selected_stem()
        if run is not None and stem is not None:
            signal.emit(run, stem)


class _VocalSplitInlineAction(QFrame):
    triggered = Signal()

    def __init__(self, button_text: str) -> None:
        super().__init__()
        self.setObjectName("VocalSplitInlineAction")
        self.setFixedSize(34, 36)
        self._action_enabled = False
        self._running = False
        self._button_text = tr(button_text)
        self._detail = ""
        self._status = ""

        self.title_label = QLabel()
        self.title_label.hide()
        self.button = SvgIconButton("split", size=34)
        self.button.setObjectName("VocalSplitActionButton")
        self.button.clicked.connect(self.triggered.emit)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ActionProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.hide()
        self.percent_label = QLabel("0%")
        self.percent_label.hide()

        self.status_label = QLabel()
        self.status_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.button)
        layout.addWidget(self.progress_bar)
        self._sync_button_enabled()
        self._sync_tooltip()

    def set_button_text(self, text: str) -> None:
        self._button_text = tr(text)
        self._sync_tooltip()

    def set_detail(self, text: str) -> None:
        self._detail = text.strip()
        self._sync_tooltip()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.button.set_theme_mode(theme_mode)

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self.progress_bar.setVisible(self._running)
        self._sync_button_enabled()

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.percent_label.setText(f"{progress}%")

    def set_status(self, text: str) -> None:
        self._status = tr(text.strip())
        self.status_label.setText(self._status)
        self._sync_tooltip()

    def set_action_enabled(self, enabled: bool) -> None:
        self._action_enabled = bool(enabled)
        self._sync_button_enabled()

    def _sync_button_enabled(self) -> None:
        self.button.setEnabled(self._action_enabled and not self._running)

    def _sync_tooltip(self) -> None:
        lines = [self._button_text]
        if self._status:
            lines.append(self._status)
        if self._detail:
            lines.append(self._detail)
        self.button.setToolTip("\n".join(lines))


class _VocalTimelineTrack(QFrame):
    activated = Signal(object)
    muted_changed = Signal(bool)
    seek_requested = Signal(float)
    reference_region_created = Signal(int, int)
    reference_region_selected = Signal(str)
    reference_region_changed = Signal(str, int, int)

    def __init__(self, stem: VocalSplitStem) -> None:
        super().__init__()
        self.setObjectName("VocalTimelineTrack")
        self.setFixedHeight(_TRACK_HEIGHT)
        self._stem = stem
        self._theme_mode = "white"

        self.header = QFrame()
        self.header.setObjectName("VocalTimelineTrackHeader")
        self.header.setFixedWidth(_TRACK_HEADER_WIDTH)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.installEventFilter(self)
        self.title_label = QLabel(tr(stem.label))
        self.title_label.setObjectName("VocalTimelineTrackTitle")
        self.title_label.setToolTip(str(stem.path))
        self.file_label = QLabel(stem.path.name)
        self.file_label.setObjectName("VocalTimelineTrackFile")
        self.file_label.setToolTip(str(stem.path))

        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(2)
        labels.addWidget(self.title_label)
        labels.addWidget(self.file_label)

        self.mute_button = FeedbackButton("M")
        self.mute_button.setObjectName("VocalTimelineMuteButton")
        self.mute_button.setCheckable(True)
        self.mute_button.setFixedSize(30, 28)
        self.mute_button.setToolTip(tr("Mute"))
        self.mute_button.toggled.connect(self._on_muted_changed)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 10, 10)
        header_layout.setSpacing(8)
        header_layout.addLayout(labels, 1)
        header_layout.addWidget(self.mute_button)

        self.waveform = _SelectableWaveform()
        self.waveform.set_path(stem.path)
        self.waveform.set_duration_ms(_stem_duration_ms(stem))
        self.waveform.setToolTip(str(stem.path))
        self.waveform.activated.connect(lambda: self.activated.emit(self._stem))
        self.waveform.seek_requested.connect(self.seek_requested.emit)
        self.waveform.reference_region_created.connect(
            self.reference_region_created.emit
        )
        self.waveform.reference_region_selected.connect(
            self.reference_region_selected.emit
        )
        self.waveform.reference_region_changed.connect(
            self.reference_region_changed.emit
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.waveform, 1)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.header and event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event if isinstance(event, QMouseEvent) else None
            if mouse_event is not None and mouse_event.button() == Qt.MouseButton.LeftButton:
                self.activated.emit(self._stem)
        return super().eventFilter(watched, event)

    def set_selected(self, selected: bool) -> None:
        self.header.setProperty("selected", selected)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    def set_muted(self, muted: bool) -> None:
        blocked = self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.blockSignals(blocked)
        self.mute_button.setProperty("muted", muted)
        self.mute_button.style().unpolish(self.mute_button)
        self.mute_button.style().polish(self.mute_button)
        self.waveform.set_muted(muted)

    def set_playhead_ratio(self, ratio: float) -> None:
        self.waveform.set_playhead_ratio(ratio)

    def set_reference_mode(self, enabled: bool) -> None:
        self.waveform.set_reference_mode(enabled)

    def set_reference_regions(
        self,
        regions: tuple[VocalReferenceRegion, ...],
        selected_region_id: str = "",
    ) -> None:
        self.waveform.set_reference_regions(regions, selected_region_id)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.waveform.set_theme_mode(theme_mode)

    def _on_muted_changed(self, muted: bool) -> None:
        self.set_muted(muted)
        self.muted_changed.emit(muted)


class _SelectableWaveform(WaveformView):
    activated = Signal()
    reference_region_created = Signal(int, int)
    reference_region_selected = Signal(str)
    reference_region_changed = Signal(str, int, int)

    HANDLE_WIDTH = 7
    MINIMUM_REGION_MS = 100

    def __init__(self) -> None:
        super().__init__()
        self._duration_ms = 0
        self._reference_mode = False
        self._reference_regions: tuple[VocalReferenceRegion, ...] = ()
        self._selected_region_id = ""
        self._draft_range: tuple[int, int] | None = None
        self._drag_region: VocalReferenceRegion | None = None
        self._drag_edge = ""
        self._selection_anchor_ms = 0
        self._selecting = False

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))

    def set_reference_mode(self, enabled: bool) -> None:
        self._reference_mode = bool(enabled)
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if self._reference_mode
            else Qt.CursorShape.PointingHandCursor
        )
        self.update()

    def set_reference_regions(
        self,
        regions: tuple[VocalReferenceRegion, ...],
        selected_region_id: str = "",
    ) -> None:
        self._reference_regions = tuple(regions)
        available = {region.region_id for region in self._reference_regions}
        self._selected_region_id = (
            selected_region_id if selected_region_id in available else ""
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._reference_regions and self._draft_range is None:
            return
        if self._duration_ms <= 0:
            return
        content = QRectF(self.rect()).adjusted(19, 15, -19, -15)
        tokens = theme_tokens(self._theme_mode)
        painter = QPainter(self)
        for region in self._reference_regions:
            drawn = (
                self._drag_region
                if self._drag_region is not None
                and self._drag_region.region_id == region.region_id
                else region
            )
            rect = self._region_rect(drawn)
            selected = region.region_id == self._selected_region_id
            fill = QColor(tokens["pair_accent"])
            fill.setAlpha(54 if selected else 24)
            painter.fillRect(
                rect,
                fill,
            )
            painter.setPen(QPen(QColor(tokens["pair_accent"]), 2 if selected else 1))
            painter.drawLine(
                QPointF(rect.left(), content.top()),
                QPointF(rect.left(), content.bottom()),
            )
            painter.drawLine(
                QPointF(rect.right(), content.top()),
                QPointF(rect.right(), content.bottom()),
            )
            if selected:
                handle = QColor(tokens["pair_accent"])
                painter.fillRect(
                    QRectF(rect.left() - 2, content.center().y() - 10, 5, 20),
                    handle,
                )
                painter.fillRect(
                    QRectF(rect.right() - 2, content.center().y() - 10, 5, 20),
                    handle,
                )
        if self._draft_range is not None:
            start_ms, end_ms = self._draft_range
            left = content.left() + content.width() * start_ms / self._duration_ms
            right = content.left() + content.width() * end_ms / self._duration_ms
            draft = QColor(tokens["pair_accent"])
            draft.setAlpha(64)
            painter.fillRect(
                QRectF(left, content.top(), max(1.0, right - left), content.height()),
                draft,
            )
            painter.setPen(QPen(QColor(tokens["pair_accent"]), 2))
            painter.drawLine(QPointF(left, content.top()), QPointF(left, content.bottom()))
            painter.drawLine(QPointF(right, content.top()), QPointF(right, content.bottom()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            if self._reference_mode and self._duration_ms > 0:
                self._selection_anchor_ms = self._position_ms(event.position().x())
                self._draft_range = (
                    self._selection_anchor_ms,
                    self._selection_anchor_ms,
                )
                self._selecting = True
                event.accept()
                return
            hit = self._region_at(event.position().x())
            if hit is not None:
                region, rect = hit
                self._selected_region_id = region.region_id
                self.reference_region_selected.emit(region.region_id)
                if abs(event.position().x() - rect.left()) <= self.HANDLE_WIDTH:
                    self._drag_region = region
                    self._drag_edge = "left"
                    event.accept()
                    return
                if abs(event.position().x() - rect.right()) <= self.HANDLE_WIDTH:
                    self._drag_region = region
                    self._drag_edge = "right"
                    event.accept()
                    return
            else:
                self._selected_region_id = ""
                self.reference_region_selected.emit("")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_region is not None and event.buttons() & Qt.MouseButton.LeftButton:
            position_ms = self._position_ms(event.position().x())
            region = self._drag_region
            if self._drag_edge == "left":
                start_ms = max(
                    0,
                    min(position_ms, region.end_ms - self.MINIMUM_REGION_MS),
                )
                self._drag_region = replace(region, start_ms=start_ms)
            else:
                end_ms = min(
                    self._duration_ms,
                    max(position_ms, region.start_ms + self.MINIMUM_REGION_MS),
                )
                self._drag_region = replace(region, end_ms=end_ms)
            self.update()
            event.accept()
            return
        if self._selecting and event.buttons() & Qt.MouseButton.LeftButton:
            current_ms = self._position_ms(event.position().x())
            selected = (
                min(self._selection_anchor_ms, current_ms),
                max(self._selection_anchor_ms, current_ms),
            )
            self._draft_range = selected
            self.update()
            event.accept()
            return
        self._update_reference_cursor(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_region is not None:
            region = self._drag_region
            original = next(
                (
                    item
                    for item in self._reference_regions
                    if item.region_id == region.region_id
                ),
                None,
            )
            self._drag_region = None
            self._drag_edge = ""
            if original is not None and region != original:
                self.reference_region_changed.emit(
                    region.region_id,
                    region.start_ms,
                    region.end_ms,
                )
            self._update_reference_cursor(event.position().x())
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            selected = self._draft_range
            self._draft_range = None
            if selected is not None and selected[1] > selected[0]:
                self.reference_region_created.emit(*selected)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._drag_region is None and not self._reference_mode:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().leaveEvent(event)

    def _position_ms(self, x_position: float) -> int:
        content = self._content_rect()
        if content.width() <= 0:
            return 0
        ratio = max(0.0, min(1.0, (x_position - content.left()) / content.width()))
        return round(self._duration_ms * ratio)

    def _content_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(19, 15, -19, -15)

    def _region_rect(self, region: VocalReferenceRegion) -> QRectF:
        content = self._content_rect()
        if self._duration_ms <= 0:
            return QRectF(content.left(), content.top(), 1, content.height())
        left = content.left() + content.width() * region.start_ms / self._duration_ms
        right = content.left() + content.width() * region.end_ms / self._duration_ms
        return QRectF(left, content.top(), max(1.0, right - left), content.height())

    def _region_at(
        self,
        x_position: float,
    ) -> tuple[VocalReferenceRegion, QRectF] | None:
        for region in reversed(self._reference_regions):
            rect = self._region_rect(region)
            if rect.left() - self.HANDLE_WIDTH <= x_position <= rect.right() + self.HANDLE_WIDTH:
                return region, rect
        return None

    def _update_reference_cursor(self, x_position: float) -> None:
        if self._reference_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        hit = self._region_at(x_position)
        if hit is None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        region, rect = hit
        selected = region.region_id == self._selected_region_id
        near_edge = (
            abs(x_position - rect.left()) <= self.HANDLE_WIDTH
            or abs(x_position - rect.right()) <= self.HANDLE_WIDTH
        )
        self.setCursor(
            Qt.CursorShape.SizeHorCursor
            if selected and near_edge
            else Qt.CursorShape.PointingHandCursor
        )


class _VocalTimelineRuler(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocalTimelineRuler")
        self.setFixedHeight(34)
        self._duration_ms = 0
        self._theme = theme_tokens("white")

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme = theme_tokens(theme_mode)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._theme["raised"]))
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.drawLine(
            _TRACK_HEADER_WIDTH,
            0,
            _TRACK_HEADER_WIDTH,
            self.height(),
        )
        if self._duration_ms <= 0:
            return
        axis_left = _TRACK_HEADER_WIDTH + 19
        axis_right = max(axis_left + 1, self.width() - 19)
        interval = _tick_interval(self._duration_ms)
        painter.setPen(QColor(self._theme["muted"]))
        for position_ms in range(0, self._duration_ms + interval, interval):
            ratio = min(1.0, position_ms / self._duration_ms)
            x = axis_left + (axis_right - axis_left) * ratio
            painter.drawLine(int(x), self.height() - 8, int(x), self.height())
            painter.drawText(
                QRectF(x + 5, 0, 60, self.height() - 7),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_duration(position_ms),
            )


def _run_duration_ms(stems: tuple[VocalSplitStem, ...]) -> int:
    durations: list[int] = []
    for stem in stems:
        try:
            durations.append(read_audio_metadata(stem.path).duration_ms)
        except Exception:
            continue
    return max(durations, default=0)


def _stem_duration_ms(stem: VocalSplitStem) -> int:
    try:
        return read_audio_metadata(stem.path).duration_ms
    except Exception:
        return 0


def _tick_interval(duration_ms: int) -> int:
    if duration_ms <= 60_000:
        return 10_000
    if duration_ms <= 240_000:
        return 30_000
    if duration_ms <= 600_000:
        return 60_000
    return 120_000


def _timeline_stylesheet(tokens: dict[str, str]) -> str:
    return f"""
        QFrame#VocalSplitTimelinePanel {{
            background: {tokens['surface']};
            border: 1px solid {tokens['border']};
            border-radius: 14px;
        }}
        QFrame#VocalTimelineSurface {{
            background: {tokens['card']};
            border: 1px solid {tokens['border']};
            border-radius: 9px;
        }}
        QFrame#VocalReferenceInlineEditor {{
            background: {tokens['raised']};
            border: none;
            border-left: 3px solid {tokens['pair_accent']};
            border-bottom: 1px solid {tokens['border']};
        }}
        QFrame#VocalReferenceToolbar {{
            background: {tokens['raised']};
            border: none;
            border-right: 1px solid {tokens['border']};
        }}
        QFrame#VocalSplitInlineAction {{
            background: transparent;
            border: none;
        }}
        QWidget#VocalTimelineContent,
        QScrollArea#VocalTimelineScroll {{
            background: transparent;
            border: none;
        }}
        QFrame#VocalTimelineTrack {{
            background: {tokens['card']};
            border: none;
            border-bottom: 1px solid {tokens['border']};
        }}
        QFrame#VocalTimelineTrackHeader {{
            background: {tokens['raised']};
            border: none;
            border-right: 1px solid {tokens['border']};
        }}
        QFrame#VocalTimelineTrackHeader:hover {{
            background: {tokens['hover']};
        }}
        QFrame#VocalTimelineTrackHeader[selected="true"] {{
            background: {tokens['selection']};
            border-left: 3px solid {tokens['pair_accent']};
            border-right: 1px solid {tokens['border']};
        }}
        QLabel#VocalTimelineTrackTitle {{
            color: {tokens['text']};
            font-weight: 700;
        }}
        QLabel#VocalTimelineTrackFile,
        QLabel#VocalTimelineGroupMeta,
        QLabel#VocalTimelineCount,
        QLabel#VocalReferenceRange,
        QLabel#VocalReferenceBackendStatus {{
            color: {tokens['muted']};
        }}
        QLabel#VocalTimelineTrackFile {{
            font-size: 10px;
        }}
        QLabel#VocalTimelineEmpty {{
            color: {tokens['muted']};
            padding: 28px;
        }}
        QPushButton#VocalTimelineMuteButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
            border: 1px solid {tokens['button_border']};
            border-radius: 6px;
            background: {tokens['card']};
            color: {tokens['muted']};
        }}
        QPushButton#VocalTimelineMuteButton:hover {{
            background: {tokens['hover']};
            color: {tokens['text']};
        }}
        QPushButton#VocalTimelineMuteButton[muted="true"] {{
            background: {tokens['warning_background']};
            border-color: {tokens['warning_border']};
            color: {tokens['warning_text']};
        }}
    """
