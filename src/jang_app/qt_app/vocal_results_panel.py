from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.localization import (
    apply_widget_language,
    set_translated_text,
    set_translated_tooltip,
)
from jang_app.qt_app.widgets import (
    ScrollSafeComboBox,
    SvgIconButton,
    TrackMixControl,
    WaveformView,
)
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalProject, VocalTake


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
        self._is_loading = False

        self.title_label = QLabel(
            "Separation Results" if mode == "separation" else "Conversion Results"
            if mode == "conversion" else "Vocal Results"
        )
        self.title_label.setObjectName("SectionTitle")

        self.result_combo = ScrollSafeComboBox()
        self.result_combo.setObjectName("TrackVersionCombo")
        self.result_combo.setMinimumWidth(320)
        self.result_combo.setMaximumWidth(760)
        if mode != "separation":
            self.result_combo.hide()
        self.result_combo.currentIndexChanged.connect(self._on_result_changed)
        self.result_selector_label = QLabel()
        self.result_selector_label.setObjectName("FieldLabel")
        set_translated_text(self.result_selector_label, "Current separation result")
        if mode != "separation":
            self.result_selector_label.hide()
        self.context_label = QLabel("")
        self.context_label.setObjectName("MutedText")
        if mode != "conversion":
            self.context_label.hide()

        self.conversion_take_label = QLabel()
        self.conversion_take_label.setObjectName("MutedText")
        set_translated_text(self.conversion_take_label, "Current converted vocal")
        if mode != "conversion":
            self.conversion_take_label.hide()

        self.conversion_take_combo = ScrollSafeComboBox()
        self.conversion_take_combo.setObjectName("TrackVersionCombo")
        self.conversion_take_combo.setMinimumWidth(320)
        self.conversion_take_combo.setMaximumWidth(620)
        if mode != "conversion":
            self.conversion_take_combo.hide()
        self.conversion_take_combo.currentIndexChanged.connect(
            self._on_conversion_take_changed
        )

        self.open_location_button = SvgIconButton("folder", size=32)
        self.open_location_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.open_location_button.clicked.connect(self._request_open_location)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.context_label, 1)
        header.addStretch(1)
        header.addWidget(self.open_location_button, 0)

        self.original_waveform = _ResultWaveform("Original Vocal")
        self.instrumental_waveform = _ResultWaveform("Instrumental")
        self.converted_waveform = _ResultWaveform(
            "Converted Vocal",
            allow_selection=mode != "conversion",
            allow_actions=True,
        )
        self.result_waveforms = {
            "all": (
                self.original_waveform,
                self.instrumental_waveform,
                self.converted_waveform,
            ),
            "separation": (self.original_waveform, self.instrumental_waveform),
            "conversion": (self.original_waveform, self.converted_waveform),
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
        if mode == "separation":
            result_selector = QHBoxLayout()
            result_selector.setContentsMargins(0, 0, 0, 0)
            result_selector.setSpacing(10)
            result_selector.addWidget(self.result_selector_label, 0)
            result_selector.addWidget(self.result_combo, 1)
            result_selector.addStretch(1)
            layout.addLayout(result_selector)
        if mode == "conversion":
            take_selector = QHBoxLayout()
            take_selector.setContentsMargins(0, 0, 0, 0)
            take_selector.setSpacing(8)
            take_selector.addWidget(self.conversion_take_label, 0)
            take_selector.addWidget(self.conversion_take_combo, 1)
            take_selector.addStretch(1)
            layout.addLayout(take_selector)
        for waveform in self.result_waveforms:
            layout.addWidget(waveform, 1)
        if mode == "separation":
            self.set_versions((), None)
        self.set_result(None)

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
        self._apply_result(result)
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
            timestamp = _display_timestamp(version.added_at)
            label = tr(version.separation_recipe_label or version.label)
            self.result_combo.addItem(f"{label}  /  {timestamp}", str(version.job_dir))
            index = self.result_combo.count() - 1
            postprocess = _postprocess_label(version.separation_postprocess_status)
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
        selected = self.converted_waveform.select_path(path)
        if selected and self._mode == "conversion":
            self._select_conversion_take(path)
        return selected

    def set_playhead_ratio(self, ratio: float) -> None:
        for waveform in self.result_waveforms:
            waveform.set_playhead_ratio(ratio)

    def set_mix_state(self, track_id: str, *, muted: bool, volume_percent: int) -> None:
        waveform = self._waveform_for_track(track_id)
        if waveform is not None:
            waveform.set_mix_state(muted=muted, volume_percent=volume_percent)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_location_button.set_theme_mode(theme_mode)
        for waveform in self.result_waveforms:
            waveform.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.converted_waveform.apply_language()
        if self._mode == "separation":
            self.set_versions(self._versions, self._selected_job_dir)
        self._apply_result(self._result)

    def _on_converted_changed(self, path: Path | None) -> None:
        if not self._is_loading:
            self.converted_selected.emit(path)

    def _on_conversion_take_changed(self) -> None:
        if self._is_loading:
            return
        value = self.conversion_take_combo.currentData()
        path = Path(value) if value else None
        if path is not None:
            self.converted_waveform.select_path(path)
        self.converted_selected.emit(path)

    def _on_result_changed(self) -> None:
        if self._is_loading:
            return
        value = self.result_combo.currentData()
        if value:
            self.result_selected.emit(Path(value))

    def _apply_result(self, result: SongVocalVersion | None) -> None:
        if self._mode == "conversion":
            self.context_label.setText(
                (
                    f"{tr(result.separation_recipe_label)} / {result.label}"
                    if result is not None
                    else tr("No separation result")
                )
            )
            self.context_label.setToolTip(str(result.job_dir) if result is not None else "")
        self.original_waveform.set_path(result.vocals_path if result is not None else None)
        self.instrumental_waveform.set_path(result.instrumental_path if result is not None else None)
        converted_paths = list(result.converted_vocal_paths) if result is not None else []
        selected_path = result.active_converted_path if result is not None else None
        takes = self._project.takes if self._project is not None else ()
        self.converted_waveform.set_takes(converted_paths, takes, selected_path)
        if self._mode == "conversion":
            self._set_conversion_takes(converted_paths, takes, selected_path)
        self.open_location_button.setEnabled(result is not None)

    def _set_conversion_takes(
        self,
        paths: list[Path],
        takes: tuple[VocalTake, ...],
        selected_path: Path | None,
    ) -> None:
        takes_by_path = {
            take.output_path.expanduser().resolve(): take
            for take in takes
        }
        self.conversion_take_combo.blockSignals(True)
        self.conversion_take_combo.clear()
        for path in paths:
            take = takes_by_path.get(path.expanduser().resolve())
            self.conversion_take_combo.addItem(
                _take_selector_label(take, path),
                str(path),
            )
            self.conversion_take_combo.setItemData(
                self.conversion_take_combo.count() - 1,
                _take_tooltip(take, path),
                Qt.ItemDataRole.ToolTipRole,
            )
        if not paths:
            self.conversion_take_combo.addItem(tr("No converted vocal"), None)
        self._select_conversion_take(selected_path)
        self.conversion_take_combo.setEnabled(bool(paths))
        self.conversion_take_combo.blockSignals(False)

    def _select_conversion_take(self, path: Path | None) -> None:
        selected_index = -1
        if path is not None:
            selected = path.expanduser().resolve()
            for index in range(self.conversion_take_combo.count()):
                value = self.conversion_take_combo.itemData(index)
                if value and Path(value).expanduser().resolve() == selected:
                    selected_index = index
                    break
        self.conversion_take_combo.setCurrentIndex(
            selected_index if selected_index >= 0 else (0 if self.conversion_take_combo.count() else -1)
        )

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
        self.remove_button = _take_action_button("trash", "Remove")
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
                _take_tooltip(take, path),
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
        return Path(data) if data else None

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
        metadata = _take_metadata(take)
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
    button = SvgIconButton(icon, size=28)
    button.setObjectName("ControlIconButton")
    set_translated_tooltip(button, tooltip)
    return button


def _take_metadata(take: VocalTake | None) -> str:
    if take is None:
        return ""
    if take.conversion is None:
        return tr("Legacy result / Conversion settings unavailable")
    conversion = take.conversion
    model = Path(conversion.voice_model).stem or conversion.voice_model
    index = Path(conversion.index_file).stem if conversion.index_file else tr("No index")
    return (
        f"{model}  /  {tr('Pitch')} {conversion.pitch:+d}  /  {index}  /  "
        f"{conversion.effective_device.upper()}  /  {_display_timestamp(take.created_at)}"
    )


def _take_tooltip(take: VocalTake | None, path: Path) -> str:
    metadata = _take_metadata(take)
    return f"{metadata}\n{path}" if metadata else str(path)


def _take_selector_label(take: VocalTake | None, path: Path) -> str:
    label = take.label if take is not None else path.stem
    if take is None:
        return label
    timestamp = _display_timestamp(take.created_at)
    if take.conversion is None:
        return f"{label}  ·  {timestamp}"
    model = Path(take.conversion.voice_model).stem or take.conversion.voice_model
    return f"{label}  ·  {model}  ·  {tr('Pitch')} {take.conversion.pitch:+d}  ·  {timestamp}"


def _display_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _postprocess_label(status: str) -> str:
    if status == "applied":
        return tr("Mix consistency applied")
    if status == "skipped":
        return tr("Mix consistency skipped")
    return ""
