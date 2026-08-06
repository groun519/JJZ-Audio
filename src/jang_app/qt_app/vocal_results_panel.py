from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.widgets import ScrollSafeComboBox, SvgIconButton, WaveformView
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalProject, VocalTake


class VocalResultsPanel(QFrame):
    converted_selected = Signal(object)
    open_location_requested = Signal(object)
    open_take_requested = Signal(object)
    rename_take_requested = Signal(object)
    remove_take_requested = Signal(object)
    reconvert_take_requested = Signal(object)
    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._result: SongVocalVersion | None = None
        self._project: VocalProject | None = None
        self._is_loading = False

        self.title_label = QLabel("Vocal Results")
        self.title_label.setObjectName("SectionTitle")

        self.open_location_button = SvgIconButton("folder", size=32)
        self.open_location_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.open_location_button.clicked.connect(self._request_open_location)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.title_label, 0)
        header.addStretch(1)
        header.addWidget(self.open_location_button, 0)

        self.original_waveform = _ResultWaveform("Original Vocal")
        self.instrumental_waveform = _ResultWaveform("Instrumental")
        self.converted_waveform = _ResultWaveform(
            "Converted Vocal",
            allow_selection=True,
            allow_actions=True,
        )
        self.result_waveforms = (
            self.original_waveform,
            self.instrumental_waveform,
            self.converted_waveform,
        )
        for waveform in self.result_waveforms:
            waveform.seek_requested.connect(self.seek_requested.emit)
        self.converted_waveform.selection_changed.connect(self._on_converted_changed)
        self.converted_waveform.open_requested.connect(self.open_take_requested.emit)
        self.converted_waveform.rename_requested.connect(self.rename_take_requested.emit)
        self.converted_waveform.remove_requested.connect(self.remove_take_requested.emit)
        self.converted_waveform.reconvert_requested.connect(self.reconvert_take_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        for waveform in self.result_waveforms:
            layout.addWidget(waveform, 1)
        self.set_result(None)

    def set_result(
        self,
        result: SongVocalVersion | None,
        project: VocalProject | None = None,
    ) -> None:
        self._is_loading = True
        self._result = result
        self._project = project
        self._apply_result(result)
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

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_location_button.set_theme_mode(theme_mode)
        for waveform in self.result_waveforms:
            waveform.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.converted_waveform.apply_language()

    def _on_converted_changed(self, path: Path | None) -> None:
        if not self._is_loading:
            self.converted_selected.emit(path)

    def _apply_result(self, result: SongVocalVersion | None) -> None:
        self.original_waveform.set_path(result.vocals_path if result is not None else None)
        self.instrumental_waveform.set_path(result.instrumental_path if result is not None else None)
        converted_paths = list(result.converted_vocal_paths) if result is not None else []
        selected_path = result.active_converted_path if result is not None else None
        takes = self._project.takes if self._project is not None else ()
        self.converted_waveform.set_takes(converted_paths, takes, selected_path)
        self.open_location_button.setEnabled(result is not None)
    def _request_open_location(self) -> None:
        if self._result is not None:
            self.open_location_requested.emit(self._result.job_dir)


class _ResultWaveform(QFrame):
    seek_requested = Signal(float)
    selection_changed = Signal(object)
    open_requested = Signal(object)
    rename_requested = Signal(object)
    remove_requested = Signal(object)
    reconvert_requested = Signal(object)

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
        for button in self.take_action_buttons:
            button.setVisible(allow_actions)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.metadata_label)
        layout.addWidget(self.waveform, 1)

    def set_path(self, path: Path | None) -> None:
        self.waveform.set_path(path)
        self.waveform.setToolTip(str(path) if path is not None else "")

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

    def set_theme_mode(self, theme_mode: str) -> None:
        self.waveform.set_theme_mode(theme_mode)
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


def _display_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value
