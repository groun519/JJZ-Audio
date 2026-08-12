from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.vocal_result_labels import (
    display_result_timestamp,
    separation_postprocess_label,
    vocal_take_metadata,
    vocal_take_tooltip,
)
from jang_app.qt_app.widgets import (
    DangerIconButton,
    ScrollSafeComboBox,
    SvgIconButton,
    TrackMixControl,
    WaveformView,
)
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalProject, VocalTake


_TAKE_ACTION_BUTTON_SIZE = 34


class VocalResultsPanel(QFrame):
    result_selected = Signal(object)
    converted_selected = Signal(object)
    open_location_requested = Signal(object)
    open_take_requested = Signal(object)
    rename_take_requested = Signal(object)
    remove_take_requested = Signal(object)
    reconvert_take_requested = Signal(object)
    seek_requested = Signal(float)
    playback_settings_changed = Signal(str, bool, int)

    def __init__(self, mode: str = "all") -> None:
        super().__init__()
        if mode not in {"all", "separation", "conversion"}:
            raise ValueError(f"Unsupported vocal results mode: {mode}")
        self.setObjectName("Panel")
        self._mode = mode
        self._result: SongVocalVersion | None = None
        self._project: VocalProject | None = None
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._selected_job_dir: Path | None = None
        self._separation_vocal_result: SongVocalVersion | None = None
        self._separation_instrumental_result: SongVocalVersion | None = None
        self._is_loading = False
        self._conversion_has_converted = False
        self._conversion_mix_initialized = False

        self.title_label = QLabel(
            "Separation Results" if mode == "separation" else "Conversion Results"
            if mode == "conversion" else "Vocal Results"
        )
        self.title_label.setObjectName("SectionTitle")

        self.song_title_label = QLabel("")
        self.song_title_label.setObjectName("VocalResultSongTitle")
        self.song_title_label.hide()

        self.result_combo = ScrollSafeComboBox()
        self.result_combo.setObjectName("TrackVersionCombo")
        self.result_combo.setMinimumWidth(320)
        self.result_combo.setMaximumWidth(760)
        self.result_combo.hide()
        self.result_combo.currentIndexChanged.connect(self._on_result_changed)
        self.result_selector_label = QLabel()
        self.result_selector_label.setObjectName("FieldLabel")
        set_translated_text(self.result_selector_label, "Current separation result")
        self.result_selector_label.hide()
        self.context_label = QLabel("")
        self.context_label.setObjectName("MutedText")
        if mode != "conversion":
            self.context_label.hide()

        self.open_location_button = SvgIconButton("folder", size=32)
        self.open_location_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.open_location_button.clicked.connect(self._request_open_location)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.song_title_label, 1)
        header.addWidget(self.open_location_button, 0)

        self.original_waveform = _ResultWaveform("Original Vocal")
        self.instrumental_waveform = _ResultWaveform("Instrumental")
        self.converted_waveform = _ResultWaveform(
            "Converted Vocal",
            allow_selection=mode != "conversion",
            allow_actions=mode == "all",
        )
        self.result_waveforms = {
            "all": (
                self.original_waveform,
                self.instrumental_waveform,
                self.converted_waveform,
            ),
            "separation": (self.original_waveform, self.instrumental_waveform),
            "conversion": (
                self.original_waveform,
                self.instrumental_waveform,
                self.converted_waveform,
            ),
        }[mode]
        for waveform in self.result_waveforms:
            waveform.seek_requested.connect(self.seek_requested.emit)
        for track_id, waveform in (
            ("original", self.original_waveform),
            ("instrumental", self.instrumental_waveform),
            ("converted", self.converted_waveform),
        ):
            waveform.playback_settings_changed.connect(
                lambda muted, volume, key=track_id: self.playback_settings_changed.emit(
                    key,
                    muted,
                    volume,
                )
            )
        self.converted_waveform.selection_changed.connect(self._on_converted_changed)
        self.converted_waveform.open_requested.connect(self.open_take_requested.emit)
        self.converted_waveform.rename_requested.connect(self.rename_take_requested.emit)
        self.converted_waveform.remove_requested.connect(self.remove_take_requested.emit)
        self.converted_waveform.reconvert_requested.connect(self.reconvert_take_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        if mode == "conversion":
            layout.addWidget(self.context_label, 0)
        for waveform in self.result_waveforms:
            layout.addWidget(waveform, 1)
        if mode == "separation":
            self.set_versions((), None)
        self.set_result(None)

    def set_song_title(self, title: str) -> None:
        value = title.strip()
        self.song_title_label.setText(value)
        self.song_title_label.setToolTip(value)
        self.song_title_label.setVisible(bool(value))

    def set_result(
        self,
        result: SongVocalVersion | None,
        project: VocalProject | None = None,
    ) -> None:
        self._is_loading = True
        self._result = result
        self._project = project
        if self._mode == "separation" and result is not None:
            resolved_result = result.job_dir.expanduser().resolve()
            has_result = any(
                version.job_dir.expanduser().resolve() == resolved_result
                for version in self._versions
            )
            if not has_result or self._selected_job_dir != resolved_result:
                versions = self._versions if has_result else (*self._versions, result)
                self.set_versions(versions, result.job_dir)
        if self._mode == "separation":
            self.set_separation_stems(result, result)
            return
        self._apply_result(result)
        self._is_loading = False

    def set_conversion_context(
        self,
        result: SongVocalVersion | None,
        *,
        converted_paths: tuple[Path, ...],
        takes: tuple[VocalTake, ...] = (),
        selected_converted_path: Path | None = None,
    ) -> None:
        if self._mode != "conversion":
            raise ValueError("Conversion context is only available in conversion mode")
        self._is_loading = True
        self._result = result
        self.context_label.setText(
            (
                f"{tr(result.separation_recipe_label)} / {result.label}"
                if result is not None
                else tr("No separation result")
            )
        )
        self.context_label.setToolTip(str(result.job_dir) if result is not None else "")
        self.original_waveform.set_path(result.vocals_path if result is not None else None)
        self.instrumental_waveform.set_path(
            result.instrumental_path if result is not None else None
        )
        self.converted_waveform.set_takes(
            list(converted_paths),
            takes,
            selected_converted_path,
        )
        self._sync_conversion_default_mix(bool(converted_paths))
        self.open_location_button.setEnabled(result is not None)
        self._is_loading = False

    def set_separation_stems(
        self,
        vocal_result: SongVocalVersion | None,
        instrumental_result: SongVocalVersion | None,
    ) -> None:
        if self._mode != "separation":
            return
        self._is_loading = True
        self._separation_vocal_result = vocal_result
        self._separation_instrumental_result = instrumental_result
        self._result = vocal_result or instrumental_result
        self.original_waveform.set_path(
            vocal_result.vocals_path if vocal_result is not None else None
        )
        self.instrumental_waveform.set_path(
            instrumental_result.instrumental_path
            if instrumental_result is not None
            else None
        )
        self.open_location_button.setEnabled(self._result is not None)
        self._is_loading = False

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
    ) -> None:
        if self._mode != "separation":
            return
        selected = selected_job_dir.expanduser().resolve() if selected_job_dir is not None else None
        self._versions = versions
        self._selected_job_dir = selected
        self._is_loading = True
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        selected_index = -1
        for version in versions:
            timestamp = display_result_timestamp(version.added_at)
            label = tr(version.separation_recipe_label or version.label)
            self.result_combo.addItem(f"{label}  /  {timestamp}", str(version.job_dir))
            index = self.result_combo.count() - 1
            postprocess = separation_postprocess_label(version.separation_postprocess_status)
            tooltip = version.separation_recipe_summary
            if postprocess:
                tooltip = f"{tooltip}\n{postprocess}"
            self.result_combo.setItemData(
                index,
                f"{tooltip}\n{version.job_dir}",
                Qt.ItemDataRole.ToolTipRole,
            )
            if selected is not None and version.job_dir.expanduser().resolve() == selected:
                selected_index = index
        if not versions:
            self.result_combo.addItem(tr("No separation result"), None)
        self.result_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.result_combo.setEnabled(bool(versions))
        self.result_combo.blockSignals(False)
        self._is_loading = False

    def current_result(self) -> SongVocalVersion | None:
        return self._result

    def current_take(self) -> VocalTake | None:
        return self.converted_waveform.current_take()

    def select_converted(self, path: Path | None) -> bool:
        return self.converted_waveform.select_path(path)

    def set_playhead_ratio(self, ratio: float) -> None:
        for waveform in self.result_waveforms:
            waveform.set_playhead_ratio(ratio)

    def set_mix_state(self, track_id: str, *, muted: bool, volume_percent: int) -> None:
        waveform = self._waveform_for_track(track_id)
        if waveform is not None:
            waveform.set_mix_state(muted=muted, volume_percent=volume_percent)

    def playback_tracks(self) -> tuple[tuple[Path, float], ...]:
        tracks: list[tuple[Path, float]] = []
        for waveform in self.result_waveforms:
            path = waveform.current_path()
            if path is None:
                continue
            volume = 0.0 if waveform.mix_control.is_muted() else waveform.mix_control.volume()
            tracks.append((path, volume))
        return tuple(tracks)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_location_button.set_theme_mode(theme_mode)
        for waveform in self.result_waveforms:
            waveform.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.converted_waveform.apply_language()
        if self._mode == "separation":
            self.set_separation_stems(
                self._separation_vocal_result,
                self._separation_instrumental_result,
            )
        else:
            self._apply_result(self._result)

    def _on_converted_changed(self, path: Path | None) -> None:
        if not self._is_loading:
            self.converted_selected.emit(path)

    def _on_result_changed(self) -> None:
        if self._is_loading:
            return
        value = self.result_combo.currentData()
        if value:
            self.result_selected.emit(Path(value))

    def _apply_result(self, result: SongVocalVersion | None) -> None:
        if self._mode == "conversion":
            converted_paths = tuple(result.converted_vocal_paths) if result is not None else ()
            selected_path = result.active_converted_path if result is not None else None
            takes = self._project.takes if self._project is not None else ()
            self.set_conversion_context(
                result,
                converted_paths=converted_paths,
                takes=takes,
                selected_converted_path=selected_path,
            )
            return
        self.original_waveform.set_path(result.vocals_path if result is not None else None)
        self.instrumental_waveform.set_path(result.instrumental_path if result is not None else None)
        converted_paths = list(result.converted_vocal_paths) if result is not None else []
        selected_path = result.active_converted_path if result is not None else None
        takes = self._project.takes if self._project is not None else ()
        self.converted_waveform.set_takes(converted_paths, takes, selected_path)
        self.open_location_button.setEnabled(result is not None)

    def _sync_conversion_default_mix(self, has_converted: bool) -> None:
        if self._conversion_mix_initialized and has_converted == self._conversion_has_converted:
            return
        self.original_waveform.set_mix_state(
            muted=has_converted,
            volume_percent=100,
        )
        self.instrumental_waveform.set_mix_state(
            muted=False,
            volume_percent=100,
        )
        self.converted_waveform.set_mix_state(
            muted=not has_converted,
            volume_percent=100,
        )
        self._conversion_has_converted = has_converted
        self._conversion_mix_initialized = True

    def _request_open_location(self) -> None:
        if self._result is not None:
            self.open_location_requested.emit(self._result.job_dir)

    def _waveform_for_track(self, track_id: str) -> _ResultWaveform | None:
        return {
            "original": self.original_waveform,
            "instrumental": self.instrumental_waveform,
            "converted": self.converted_waveform,
        }.get(track_id)


class _ResultWaveform(QFrame):
    seek_requested = Signal(float)
    selection_changed = Signal(object)
    open_requested = Signal(object)
    rename_requested = Signal(object)
    remove_requested = Signal(object)
    reconvert_requested = Signal(object)
    playback_settings_changed = Signal(bool, int)

    def __init__(
        self,
        title: str,
        *,
        allow_selection: bool = False,
        allow_actions: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("InsetCard")
        self._is_loading = False
        self._allow_selection = allow_selection
        self._takes_by_path: dict[Path, VocalTake] = {}
        self._current_path: Path | None = None

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.path_combo = ScrollSafeComboBox()
        self.path_combo.setObjectName("TrackVersionCombo")
        self.path_combo.setMinimumWidth(220)
        self.path_combo.setVisible(False)
        self.path_combo.currentIndexChanged.connect(self._on_selection_changed)

        self.reconvert_button = _take_action_button("repeat", "Convert again")
        self.rename_button = _take_action_button("edit", "Rename")
        self.open_button = _take_action_button("folder", "Open file location")
        self.remove_button = DangerIconButton(size=_TAKE_ACTION_BUTTON_SIZE)
        set_translated_tooltip(self.remove_button, "Remove")
        self.take_action_buttons = (
            self.reconvert_button,
            self.rename_button,
            self.open_button,
            self.remove_button,
        )
        if not allow_actions:
            for button in self.take_action_buttons:
                button.hide()
        self.reconvert_button.clicked.connect(
            lambda: self._emit_for_current(self.reconvert_requested)
        )
        self.rename_button.clicked.connect(lambda: self._emit_for_current(self.rename_requested))
        self.open_button.clicked.connect(lambda: self._emit_for_current(self.open_requested))
        self.remove_button.clicked.connect(lambda: self._emit_for_current(self.remove_requested))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.path_combo, 1)
        for button in self.take_action_buttons:
            header.addWidget(button, 0)

        self.metadata_label = QLabel("")
        self.metadata_label.setObjectName("VocalTakeMetadata")
        self.metadata_label.setVisible(False)

        self.waveform = WaveformView()
        self.waveform.setMinimumHeight(82)
        self.waveform.seek_requested.connect(self.seek_requested.emit)
        self.mix_control = TrackMixControl()
        self.mix_control.settings_changed.connect(self._on_playback_settings_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.metadata_label)
        layout.addWidget(self.waveform, 1)
        layout.addWidget(self.mix_control, 0)

    def set_path(self, path: Path | None) -> None:
        self._current_path = path
        self.waveform.set_path(path)
        self.waveform.setToolTip(str(path) if path is not None else "")
        self.mix_control.set_controls_enabled(path is not None)

    def set_options(self, paths: list[Path], selected_path: Path | None) -> None:
        self.set_takes(paths, (), selected_path)

    def set_takes(
        self,
        paths: list[Path],
        takes: tuple[VocalTake, ...],
        selected_path: Path | None,
    ) -> None:
        self._is_loading = True
        self._takes_by_path = {
            take.output_path.expanduser().resolve(): take
            for take in takes
        }
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        for path in paths:
            take = self._take_for_path(path)
            self.path_combo.addItem(take.label if take is not None else path.stem, str(path))
            self.path_combo.setItemData(
                self.path_combo.count() - 1,
                vocal_take_tooltip(take, path),
                Qt.ItemDataRole.ToolTipRole,
            )
        selected_index = self._path_index(selected_path)
        self.path_combo.setCurrentIndex(selected_index if selected_index >= 0 else (0 if paths else -1))
        self.path_combo.setEnabled(bool(paths))
        self.path_combo.setVisible(self._allow_selection and len(paths) > 1)
        self.path_combo.blockSignals(False)
        self._apply_current_take()
        self._is_loading = False

    def select_path(self, path: Path | None) -> bool:
        index = self._path_index(path)
        if index < 0:
            return False
        self._is_loading = True
        was_blocked = self.path_combo.blockSignals(True)
        self.path_combo.setCurrentIndex(index)
        self.path_combo.blockSignals(was_blocked)
        self._apply_current_take()
        self._is_loading = False
        return True

    def current_path(self) -> Path | None:
        data = self.path_combo.currentData()
        if data:
            return Path(data)
        return self._current_path

    def current_take(self) -> VocalTake | None:
        path = self.current_path()
        return self._take_for_path(path) if path is not None else None

    def set_playhead_ratio(self, ratio: float) -> None:
        self.waveform.set_playhead_ratio(ratio)

    def set_mix_state(self, *, muted: bool, volume_percent: int) -> None:
        self.mix_control.set_mix_state(muted=muted, volume_percent=volume_percent)
        self.waveform.set_muted(muted)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.waveform.set_theme_mode(theme_mode)
        self.mix_control.set_theme_mode(theme_mode)
        for button in self.take_action_buttons:
            button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        for button, tooltip in (
            (self.reconvert_button, "Convert again"),
            (self.rename_button, "Rename"),
            (self.open_button, "Open file location"),
            (self.remove_button, "Remove"),
        ):
            set_translated_tooltip(button, tooltip)
        self._apply_current_take()

    def _on_selection_changed(self) -> None:
        path = self.current_path()
        self._apply_current_take()
        if not self._is_loading:
            self.selection_changed.emit(path)

    def _on_playback_settings_changed(self) -> None:
        self.waveform.set_muted(self.mix_control.is_muted())
        self.playback_settings_changed.emit(
            self.mix_control.is_muted(),
            self.mix_control.volume_percent(),
        )

    def _apply_current_take(self) -> None:
        path = self.current_path()
        take = self.current_take()
        self.set_path(path)
        metadata = vocal_take_metadata(take)
        self.metadata_label.setText(metadata)
        self.metadata_label.setVisible(bool(metadata))
        has_path = path is not None
        for button in self.take_action_buttons:
            button.setEnabled(has_path)

    def _take_for_path(self, path: Path) -> VocalTake | None:
        return self._takes_by_path.get(path.expanduser().resolve())

    def _emit_for_current(self, signal: Signal) -> None:
        path = self.current_path()
        if path is not None:
            signal.emit(path)

    def _path_index(self, path: Path | None) -> int:
        if path is None:
            return -1
        resolved = path.expanduser().resolve()
        for index in range(self.path_combo.count()):
            data = self.path_combo.itemData(index)
            if data and Path(data).expanduser().resolve() == resolved:
                return index
        return -1


def _take_action_button(icon: str, tooltip: str) -> SvgIconButton:
    button = SvgIconButton(icon, size=_TAKE_ACTION_BUTTON_SIZE)
    button.setObjectName("ControlIconButton")
    set_translated_tooltip(button, tooltip)
    return button
