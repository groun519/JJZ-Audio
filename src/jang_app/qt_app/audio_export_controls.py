from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.export_action_footer import ExportActionFooter
from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton, InfoPopoverButton, ScrollSafeComboBox
from jang_app.services.audio_export_settings import (
    AUDIO_FORMAT_FLAC,
    AUDIO_FORMAT_MP3,
    AUDIO_FORMAT_OPUS,
    AUDIO_FORMAT_WAV,
    DISCORD_TARGET_BYTES,
    NORMALIZATION_OFF,
    NORMALIZATION_OVERLOAD,
    NORMALIZATION_STREAMING,
    PRESET_CUSTOM,
    PRESET_DISCORD_10MB,
    PRESET_LOSSLESS_FLAC,
    PRESET_MASTER_WAV,
    PRESET_SHARE_MP3,
    AudioExportSettings,
    audio_export_preset,
    discord_opus_bitrate_kbps,
    estimated_opus_size_bytes,
)
from jang_app.services.i18n import tr


class AudioExportControls(QFrame):
    settings_changed = Signal(object)
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("AudioExportControls")
        self._updating = False
        self._action_enabled = True
        self._running = False
        self._duration_ms = 0

        title = QLabel()
        title.setObjectName("ExportSettingsTitle")
        set_translated_text(title, "Audio Export")

        self.summary_label = QLabel()
        self.summary_label.setObjectName("AudioExportSummary")
        self.summary_label.setWordWrap(True)

        self.preset_buttons: dict[str, FeedbackButton] = {}
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        preset_bar = QFrame()
        preset_bar.setObjectName("ExportPresetBar")
        preset_bar_layout = QGridLayout(preset_bar)
        preset_bar_layout.setContentsMargins(4, 4, 4, 4)
        preset_bar_layout.setSpacing(4)
        for preset_id, label, row, column, column_span in (
            (PRESET_MASTER_WAV, "Master WAV", 0, 0, 1),
            (PRESET_LOSSLESS_FLAC, "Lossless FLAC", 0, 1, 1),
            (PRESET_SHARE_MP3, "Share MP3", 0, 2, 1),
            (PRESET_DISCORD_10MB, "Discord 10MB", 1, 0, 2),
            (PRESET_CUSTOM, "Custom", 1, 2, 1),
        ):
            button = FeedbackButton()
            button.setObjectName("ExportPresetButton")
            button.setCheckable(True)
            set_translated_text(button, label)
            button.clicked.connect(
                lambda _checked=False, selected=preset_id: self._select_preset_from_button(selected)
            )
            self.preset_group.addButton(button)
            self.preset_buttons[preset_id] = button
            preset_bar_layout.addWidget(button, row, column, 1, column_span)

        self.format_combo = ScrollSafeComboBox()
        self.format_combo.setObjectName("ExportSettingCombo")
        self.sample_rate_combo = ScrollSafeComboBox()
        self.sample_rate_combo.setObjectName("ExportSettingCombo")
        self.bit_depth_combo = ScrollSafeComboBox()
        self.bit_depth_combo.setObjectName("ExportSettingCombo")
        self.normalization_combo = ScrollSafeComboBox()
        self.normalization_combo.setObjectName("ExportSettingCombo")
        self.bitrate_combo = ScrollSafeComboBox()
        self.bitrate_combo.setObjectName("ExportSettingCombo")

        self.dither_check = QCheckBox()
        self.dither_check.setObjectName("ExportDitherCheck")
        set_translated_text(self.dither_check, "Use dither")

        self.format_label, self.format_info = _field_header("Format")
        self.sample_rate_label, self.sample_rate_info = _field_header("Sample Rate")
        self.bit_depth_label, self.bit_depth_info = _field_header("Bit Depth")
        self.normalization_label, self.normalization_info = _field_header("Output Level")
        self.bitrate_label, self.bitrate_info = _field_header("Compressed Bitrate")

        fields = QGridLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(10)
        fields.addWidget(self.format_label, 0, 0)
        fields.addWidget(self.sample_rate_label, 0, 1)
        fields.addWidget(self.format_combo, 1, 0)
        fields.addWidget(self.sample_rate_combo, 1, 1)
        fields.addWidget(self.bit_depth_label, 2, 0)
        fields.addWidget(self.normalization_label, 2, 1)
        fields.addWidget(self.bit_depth_combo, 3, 0)
        fields.addWidget(self.normalization_combo, 3, 1)
        fields.addWidget(self.bitrate_label, 4, 0)
        fields.addWidget(self.bitrate_combo, 5, 0)
        fields.addWidget(self.dither_check, 5, 1)
        fields.setColumnStretch(0, 1)
        fields.setColumnStretch(1, 1)

        self.action_footer = ExportActionFooter("Export")
        self.action_footer.triggered.connect(self.triggered.emit)
        self.export_button = self.action_footer.button
        self.progress_bar = self.action_footer.progress_bar
        self.percent_label = self.action_footer.percent_label
        self.status_label = self.action_footer.status_label

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(preset_bar)
        layout.addWidget(self.summary_label)
        layout.addLayout(fields)
        layout.addWidget(self.action_footer)

        for combo in (
            self.format_combo,
            self.sample_rate_combo,
            self.bit_depth_combo,
            self.normalization_combo,
            self.bitrate_combo,
        ):
            combo.currentIndexChanged.connect(self._on_detail_changed)
        self.dither_check.toggled.connect(self._on_detail_changed)

        self.apply_language()
        self._apply_settings(audio_export_preset(PRESET_MASTER_WAV))

    def settings(self) -> AudioExportSettings:
        audio_format = str(self.format_combo.currentData() or AUDIO_FORMAT_WAV)
        bitrate_value = int(self.bitrate_combo.currentData() or 0)
        automatic_opus = audio_format == AUDIO_FORMAT_OPUS and bitrate_value == 0
        return AudioExportSettings(
            preset_id=self._selected_preset_id(),
            format=audio_format,
            sample_rate=self.sample_rate_combo.currentData(),
            bit_depth=int(self.bit_depth_combo.currentData() or 24),
            normalization=str(self.normalization_combo.currentData() or NORMALIZATION_OVERLOAD),
            dither=self.dither_check.isChecked()
            and audio_format not in {AUDIO_FORMAT_MP3, AUDIO_FORMAT_OPUS},
            mp3_bitrate_kbps=bitrate_value or 320,
            opus_bitrate_kbps=None if automatic_opus else (bitrate_value or 192),
            target_size_bytes=DISCORD_TARGET_BYTES if automatic_opus else None,
        )

    def select_preset(self, preset_id: str) -> None:
        if preset_id not in self.preset_buttons:
            raise ValueError(f"Unknown audio export preset: {preset_id}")
        self._apply_settings(audio_export_preset(preset_id))

    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self._update_summary()

    def set_action_enabled(self, is_enabled: bool) -> None:
        self._action_enabled = is_enabled
        self.action_footer.set_action_enabled(is_enabled)

    def set_running(self, is_running: bool) -> None:
        self._running = is_running
        for button in self.preset_buttons.values():
            button.setEnabled(not is_running)
        for control in (
            self.format_combo,
            self.sample_rate_combo,
            self.bit_depth_combo,
            self.normalization_combo,
            self.bitrate_combo,
            self.dither_check,
        ):
            control.setEnabled(not is_running)
        self._sync_format_controls()
        self.action_footer.set_running(is_running)

    def set_progress(self, value: int) -> None:
        self.action_footer.set_progress(value)

    def set_status(self, text: str) -> None:
        self.action_footer.set_status(text)

    def apply_language(self) -> None:
        selected = {
            "format": self.format_combo.currentData(),
            "sample_rate": self.sample_rate_combo.currentData(),
            "bit_depth": self.bit_depth_combo.currentData(),
            "normalization": self.normalization_combo.currentData(),
            "bitrate": self.bitrate_combo.currentData(),
        }
        self._updating = True
        for button in self.preset_buttons.values():
            apply_widget_language(button)
        _set_combo_items(
            self.format_combo,
            (
                ("WAV", AUDIO_FORMAT_WAV),
                ("FLAC", AUDIO_FORMAT_FLAC),
                ("MP3", AUDIO_FORMAT_MP3),
                ("Opus (Ogg)", AUDIO_FORMAT_OPUS),
            ),
            selected["format"] or AUDIO_FORMAT_WAV,
        )
        _set_combo_items(
            self.sample_rate_combo,
            (("Match Source", None), ("44.1 kHz", 44_100), ("48 kHz", 48_000)),
            selected["sample_rate"],
        )
        self._populate_bit_depths(int(selected["bit_depth"] or 24))
        _set_combo_items(
            self.normalization_combo,
            (
                ("Unchanged", NORMALIZATION_OFF),
                ("Overload Protection", NORMALIZATION_OVERLOAD),
                ("Streaming (-14 LUFS)", NORMALIZATION_STREAMING),
            ),
            selected["normalization"] or NORMALIZATION_OVERLOAD,
        )
        selected_bitrate = selected["bitrate"]
        self._populate_bitrates(
            int(selected_bitrate) if selected_bitrate is not None else 320
        )
        self._updating = False
        apply_widget_language(self)
        self._apply_help_text()
        self._sync_format_controls()
        self._update_summary()

    def _select_preset_from_button(self, preset_id: str) -> None:
        if preset_id == PRESET_CUSTOM:
            self._update_summary()
            self.settings_changed.emit(self.settings())
            return
        self._apply_settings(audio_export_preset(preset_id))

    def _on_detail_changed(self) -> None:
        if self._updating:
            return
        self._updating = True
        self.preset_buttons[PRESET_CUSTOM].setChecked(True)
        self._sync_format_controls()
        self._updating = False
        self._update_summary()
        self.settings_changed.emit(self.settings())

    def _apply_settings(self, settings: AudioExportSettings) -> None:
        self._updating = True
        self.preset_buttons[settings.preset_id].setChecked(True)
        _select_data(self.format_combo, settings.format)
        _select_data(self.sample_rate_combo, settings.sample_rate)
        self._populate_bit_depths(settings.bit_depth)
        _select_data(self.normalization_combo, settings.normalization)
        self._populate_bitrates(
            0
            if settings.format == AUDIO_FORMAT_OPUS and settings.target_size_bytes is not None
            else (
                settings.opus_bitrate_kbps
                if settings.format == AUDIO_FORMAT_OPUS
                else settings.mp3_bitrate_kbps
            )
        )
        self.dither_check.setChecked(settings.dither)
        self._sync_format_controls()
        self._updating = False
        self._update_summary()
        self.settings_changed.emit(self.settings())

    def _populate_bit_depths(self, selected: int) -> None:
        audio_format = str(self.format_combo.currentData() or AUDIO_FORMAT_WAV)
        values = (16, 24) if audio_format == AUDIO_FORMAT_FLAC else (16, 24, 32)
        labels = tuple(("32-bit Float" if value == 32 else f"{value}-bit", value) for value in values)
        fallback = selected if selected in values else 24
        _set_combo_items(self.bit_depth_combo, labels, fallback)

    def _populate_bitrates(self, selected: int | None) -> None:
        audio_format = str(self.format_combo.currentData() or AUDIO_FORMAT_WAV)
        if audio_format == AUDIO_FORMAT_OPUS:
            items = (("Auto (under 10 MB)", 0),) + tuple(
                (f"{value} kbps", value) for value in (64, 96, 128, 160, 192, 256, 320)
            )
            fallback = selected if selected in {0, 64, 96, 128, 160, 192, 256, 320} else 192
        else:
            items = tuple((f"{value} kbps", value) for value in (128, 192, 256, 320))
            fallback = selected if selected in {128, 192, 256, 320} else 320
        _set_combo_items(self.bitrate_combo, items, fallback)

    def _sync_format_controls(self) -> None:
        audio_format = str(self.format_combo.currentData() or AUDIO_FORMAT_WAV)
        current_depth = int(self.bit_depth_combo.currentData() or 24)
        current_bitrate = self.bitrate_combo.currentData()
        self._populate_bit_depths(current_depth)
        is_mp3 = audio_format == AUDIO_FORMAT_MP3
        is_opus = audio_format == AUDIO_FORMAT_OPUS
        is_compressed = is_mp3 or is_opus
        self._populate_bitrates(
            int(current_bitrate) if current_bitrate is not None else None
        )
        if is_opus:
            _select_data(self.sample_rate_combo, 48_000)
        controls_enabled = not self._running
        self.sample_rate_combo.setEnabled(controls_enabled and not is_opus)
        self.bit_depth_combo.setEnabled(controls_enabled and not is_compressed)
        self.dither_check.setEnabled(controls_enabled and not is_compressed)
        self.bitrate_combo.setEnabled(controls_enabled and is_compressed)
        self.bitrate_label.setEnabled(is_compressed)

    def _update_summary(self) -> None:
        settings = self.settings()
        rate = tr("Match Source") if settings.sample_rate is None else f"{settings.sample_rate / 1000:g} kHz"
        if settings.format == AUDIO_FORMAT_OPUS:
            detail = self._opus_summary(settings)
        elif settings.format == AUDIO_FORMAT_MP3:
            detail = f"MP3 / {rate} / {settings.mp3_bitrate_kbps} kbps"
        else:
            depth = tr("32-bit Float") if settings.bit_depth == 32 else f"{settings.bit_depth}-bit"
            detail = f"{settings.format.upper()} / {rate} / {depth}"
        level = {
            NORMALIZATION_OFF: tr("Unchanged"),
            NORMALIZATION_OVERLOAD: tr("Overload Protection"),
            NORMALIZATION_STREAMING: tr("Streaming (-14 LUFS)"),
        }[settings.normalization]
        self.summary_label.setText(f"{detail}  ·  {level}")

    def _opus_summary(self, settings: AudioExportSettings) -> str:
        if settings.target_size_bytes is None:
            return f"Opus / 48 kHz / {settings.opus_bitrate_kbps or 192} kbps"
        if self._duration_ms <= 0:
            return f"Opus / 48 kHz / {tr('Auto under 10 MB')}"
        try:
            bitrate = discord_opus_bitrate_kbps(
                self._duration_ms / 1000,
                settings.target_size_bytes,
            )
        except ValueError:
            return tr("This song is too long to keep music quality under 10 MB.")
        estimated = min(
            settings.target_size_bytes,
            estimated_opus_size_bytes(self._duration_ms / 1000, bitrate),
        )
        quality = _opus_quality_label(bitrate)
        return (
            f"Opus / 48 kHz / {bitrate} kbps / "
            f"{tr('About')} {estimated / 1_000_000:.1f} MB / {tr(quality)}"
        )

    def _apply_help_text(self) -> None:
        self.format_info.set_content(
            tr("Format"),
            tr("WAV preserves the master, FLAC is lossless, MP3 is universal, and Opus gives the best quality per file size."),
        )
        self.sample_rate_info.set_content(
            tr("Sample Rate"),
            tr("Match Source avoids unnecessary resampling. Use 48 kHz for video workflows."),
        )
        self.bit_depth_info.set_content(
            tr("Bit Depth"),
            tr("24-bit is the recommended master quality. 32-bit float keeps extra editing headroom."),
        )
        self.normalization_info.set_content(
            tr("Output Level"),
            tr("Overload protection only turns down clipping mixes. Streaming targets -14 LUFS."),
        )
        self.bitrate_info.set_content(
            tr("Compressed Bitrate"),
            tr(
                "Higher bitrates retain more detail. Discord mode calculates the highest safe "
                "bitrate under 10 MB."
            ),
        )

    def _selected_preset_id(self) -> str:
        return next(
            (preset_id for preset_id, button in self.preset_buttons.items() if button.isChecked()),
            PRESET_MASTER_WAV,
        )

def _field_header(text: str) -> tuple[QWidget, InfoPopoverButton]:
    header = QWidget()
    header.setObjectName("ExportFieldHeader")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel()
    label.setObjectName("ExportFieldLabel")
    set_translated_text(label, text)
    info = InfoPopoverButton()
    layout.addWidget(label)
    layout.addWidget(info)
    layout.addStretch(1)
    return header, info


def _set_combo_items(combo: ScrollSafeComboBox, items: tuple[tuple[str, object], ...], selected: object) -> None:
    combo.blockSignals(True)
    combo.clear()
    for label, value in items:
        combo.addItem(tr(label), value)
    _select_data(combo, selected)
    combo.blockSignals(False)


def _select_data(combo: ScrollSafeComboBox, value: object) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _opus_quality_label(bitrate_kbps: int) -> str:
    if bitrate_kbps >= 256:
        return "Very High Quality"
    if bitrate_kbps >= 192:
        return "High Quality"
    if bitrate_kbps >= 128:
        return "Good Quality"
    return "Reduced Quality"
