from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import ScrollSafeComboBox, SvgIconButton, WaveformView
from jang_app.services.song_library import SongVocalVersion


class VocalResultsPanel(QFrame):
    converted_selected = Signal(object)
    open_location_requested = Signal(object)
    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._result: SongVocalVersion | None = None
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
        self.converted_waveform = _ResultWaveform("Converted Vocal", allow_selection=True)
        self.result_waveforms = (
            self.original_waveform,
            self.instrumental_waveform,
            self.converted_waveform,
        )
        for waveform in self.result_waveforms:
            waveform.seek_requested.connect(self.seek_requested.emit)
        self.converted_waveform.selection_changed.connect(self._on_converted_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        for waveform in self.result_waveforms:
            layout.addWidget(waveform, 1)
        self.set_result(None)

    def set_result(self, result: SongVocalVersion | None) -> None:
        self._is_loading = True
        self._result = result
        self._apply_result(result)
        self._is_loading = False

    def current_result(self) -> SongVocalVersion | None:
        return self._result

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

    def _on_converted_changed(self, path: Path | None) -> None:
        if not self._is_loading:
            self.converted_selected.emit(path)

    def _apply_result(self, result: SongVocalVersion | None) -> None:
        self.original_waveform.set_path(result.vocals_path if result is not None else None)
        self.instrumental_waveform.set_path(result.instrumental_path if result is not None else None)
        converted_paths = list(result.converted_vocal_paths) if result is not None else []
        selected_path = result.active_converted_path if result is not None else None
        self.converted_waveform.set_options(converted_paths, selected_path)
        self.open_location_button.setEnabled(result is not None)

    def _request_open_location(self) -> None:
        if self._result is not None:
            self.open_location_requested.emit(self._result.job_dir)


class _ResultWaveform(QFrame):
    seek_requested = Signal(float)
    selection_changed = Signal(object)

    def __init__(self, title: str, *, allow_selection: bool = False) -> None:
        super().__init__()
        self.setObjectName("InsetCard")
        self._is_loading = False
        self._allow_selection = allow_selection

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.path_combo = ScrollSafeComboBox()
        self.path_combo.setObjectName("TrackVersionCombo")
        self.path_combo.setMinimumWidth(220)
        self.path_combo.setVisible(False)
        self.path_combo.currentIndexChanged.connect(self._on_selection_changed)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.path_combo, 1)

        self.waveform = WaveformView()
        self.waveform.setMinimumHeight(82)
        self.waveform.seek_requested.connect(self.seek_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.waveform, 1)

    def set_path(self, path: Path | None) -> None:
        self.waveform.set_path(path)
        self.waveform.setToolTip(str(path) if path is not None else "")

    def set_options(self, paths: list[Path], selected_path: Path | None) -> None:
        self._is_loading = True
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        for path in paths:
            self.path_combo.addItem(path.stem, str(path))
        selected_index = self._path_index(selected_path)
        self.path_combo.setCurrentIndex(selected_index if selected_index >= 0 else (0 if paths else -1))
        self.path_combo.setEnabled(bool(paths))
        self.path_combo.setVisible(self._allow_selection and len(paths) > 1)
        self.path_combo.blockSignals(False)
        self.set_path(self.current_path())
        self._is_loading = False

    def select_path(self, path: Path | None) -> bool:
        index = self._path_index(path)
        if index < 0:
            return False
        self._is_loading = True
        was_blocked = self.path_combo.blockSignals(True)
        self.path_combo.setCurrentIndex(index)
        self.path_combo.blockSignals(was_blocked)
        self.set_path(self.current_path())
        self._is_loading = False
        return True

    def current_path(self) -> Path | None:
        data = self.path_combo.currentData()
        return Path(data) if data else None

    def set_playhead_ratio(self, ratio: float) -> None:
        self.waveform.set_playhead_ratio(ratio)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.waveform.set_theme_mode(theme_mode)

    def _on_selection_changed(self) -> None:
        path = self.current_path()
        self.set_path(path)
        if not self._is_loading:
            self.selection_changed.emit(path)

    def _path_index(self, path: Path | None) -> int:
        if path is None:
            return -1
        resolved = path.expanduser().resolve()
        for index in range(self.path_combo.count()):
            data = self.path_combo.itemData(index)
            if data and Path(data).expanduser().resolve() == resolved:
                return index
        return -1
