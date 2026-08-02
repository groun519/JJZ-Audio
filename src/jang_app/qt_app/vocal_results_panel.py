from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import FeedbackButton, ScrollSafeComboBox, SvgIconButton, WaveformView
from jang_app.services.song_library import SongVocalVersion


class VocalResultsPanel(QFrame):
    output_selected = Signal(object)
    converted_selected = Signal(object)
    open_location_requested = Signal(object)
    remove_output_requested = Signal(object)
    open_studio_requested = Signal()
    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._versions_by_path: dict[Path, SongVocalVersion] = {}
        self._is_loading = False

        self.title_label = QLabel("Vocal Results")
        self.title_label.setObjectName("SectionTitle")

        self.version_combo = ScrollSafeComboBox()
        self.version_combo.setObjectName("VocalVersionCombo")
        self.version_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)

        self.open_location_button = SvgIconButton("folder", size=32)
        self.open_location_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_location_button, "Open file location")
        self.open_location_button.clicked.connect(self._request_open_location)

        self.remove_output_button = SvgIconButton("trash", size=32)
        self.remove_output_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.remove_output_button, "Remove")
        self.remove_output_button.clicked.connect(self._request_remove_output)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.title_label, 0)
        header.addWidget(self.version_combo, 1)
        header.addWidget(self.open_location_button, 0)
        header.addWidget(self.remove_output_button, 0)

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

        self.open_studio_button = FeedbackButton("Open Studio")
        self.open_studio_button.setObjectName("PrimaryButton")
        self.open_studio_button.setFixedWidth(148)
        self.open_studio_button.clicked.connect(self.open_studio_requested.emit)

        studio_actions = QHBoxLayout()
        studio_actions.setContentsMargins(0, 0, 0, 0)
        studio_actions.addStretch(1)
        studio_actions.addWidget(self.open_studio_button, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        for waveform in self.result_waveforms:
            layout.addWidget(waveform, 1)
        layout.addLayout(studio_actions)
        self._set_controls_enabled(False)

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        active_job_dir: Path | None,
    ) -> None:
        self._is_loading = True
        self._versions = versions
        self._versions_by_path = {version.job_dir.expanduser().resolve(): version for version in versions}
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for version in versions:
            self.version_combo.addItem(_version_label(version), str(version.job_dir))
        selected_index = self._version_index(active_job_dir)
        self.version_combo.setCurrentIndex(selected_index if selected_index >= 0 else (0 if versions else -1))
        self.version_combo.blockSignals(False)
        self._apply_version(self.current_version())
        self._is_loading = False

    def current_version(self) -> SongVocalVersion | None:
        data = self.version_combo.currentData()
        if not data:
            return None
        return self._versions_by_path.get(Path(data).expanduser().resolve())

    def select_converted(self, path: Path | None) -> bool:
        return self.converted_waveform.select_path(path)

    def set_playhead_ratio(self, ratio: float) -> None:
        for waveform in self.result_waveforms:
            waveform.set_playhead_ratio(ratio)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_location_button.set_theme_mode(theme_mode)
        self.remove_output_button.set_theme_mode(theme_mode)
        for waveform in self.result_waveforms:
            waveform.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.open_location_button, "Open file location")
        set_translated_tooltip(self.remove_output_button, "Remove")

    def _on_version_changed(self) -> None:
        version = self.current_version()
        self._apply_version(version)
        if not self._is_loading and version is not None:
            self.output_selected.emit(version.job_dir)

    def _on_converted_changed(self, path: Path | None) -> None:
        if not self._is_loading:
            self.converted_selected.emit(path)

    def _apply_version(self, version: SongVocalVersion | None) -> None:
        self.original_waveform.set_path(version.vocals_path if version is not None else None)
        self.instrumental_waveform.set_path(version.instrumental_path if version is not None else None)
        converted_paths = list(version.converted_vocal_paths) if version is not None else []
        selected_path = version.active_converted_path if version is not None else None
        self.converted_waveform.set_options(converted_paths, selected_path)
        self._set_controls_enabled(version is not None)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.open_location_button.setEnabled(enabled)
        self.remove_output_button.setEnabled(enabled)
        self.open_studio_button.setEnabled(enabled)

    def _request_open_location(self) -> None:
        version = self.current_version()
        if version is not None:
            self.open_location_requested.emit(version.job_dir)

    def _request_remove_output(self) -> None:
        version = self.current_version()
        if version is not None:
            self.remove_output_requested.emit(version.job_dir)

    def _version_index(self, job_dir: Path | None) -> int:
        if job_dir is None:
            return -1
        resolved = job_dir.expanduser().resolve()
        for index in range(self.version_combo.count()):
            data = self.version_combo.itemData(index)
            if data and Path(data).expanduser().resolve() == resolved:
                return index
        return -1


class _ResultWaveform(QFrame):
    seek_requested = Signal(float)
    selection_changed = Signal(object)

    def __init__(self, title: str, *, allow_selection: bool = False) -> None:
        super().__init__()
        self.setObjectName("InsetCard")
        self._is_loading = False

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.path_combo = ScrollSafeComboBox()
        self.path_combo.setObjectName("TrackVersionCombo")
        self.path_combo.setMinimumWidth(220)
        self.path_combo.setVisible(allow_selection)
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


def _version_label(version: SongVocalVersion) -> str:
    timestamp = _format_timestamp(version.added_at)
    return f"{version.label}  /  {timestamp}" if timestamp else version.label


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%y/%m/%d %H:%M")
    except ValueError:
        return ""
