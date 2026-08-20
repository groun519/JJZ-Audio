from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.export_action_footer import ExportActionFooter
from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton, InfoPopoverButton, ScrollSafeComboBox
from jang_app.services.i18n import tr
from jang_app.services.video_export_settings import (
    ENCODING_FAST,
    ENCODING_SLOW,
    ENCODING_STANDARD,
    PRESET_COMPACT_720P,
    PRESET_CUSTOM,
    PRESET_DISCORD_10MB,
    PRESET_HIGH_QUALITY,
    PRESET_YOUTUBE_1080P,
    VIDEO_TARGET_10MB_BYTES,
    VideoExportSettings,
    video_export_preset,
)


class VideoExportControls(QFrame):
    settings_changed = Signal(object)
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VideoExportControls")
        self._updating = False
        self._running = False

        title = QLabel()
        title.setObjectName("ExportSettingsTitle")
        set_translated_text(title, "Video Export")

        self.summary_label = QLabel()
        self.summary_label.setObjectName("AudioExportSummary")
        self.summary_label.setWordWrap(True)

        self.preset_buttons: dict[str, FeedbackButton] = {}
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        preset_bar = QFrame()
        preset_bar.setObjectName("ExportPresetBar")
        preset_layout = QHBoxLayout(preset_bar)
        preset_layout.setContentsMargins(4, 4, 4, 4)
        preset_layout.setSpacing(4)
        for preset_id, label in (
            (PRESET_YOUTUBE_1080P, "1080p"),
            (PRESET_HIGH_QUALITY, "High"),
            (PRESET_COMPACT_720P, "720p"),
            (PRESET_DISCORD_10MB, "10MB"),
            (PRESET_CUSTOM, "Custom"),
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
            preset_layout.addWidget(button, 1)

        self.resolution_combo = _setting_combo()
        self.frame_rate_combo = _setting_combo()
        self.quality_combo = _setting_combo()
        self.encoding_combo = _setting_combo()
        self.audio_bitrate_combo = _setting_combo()

        self.resolution_label, self.resolution_info = _field_header("Resolution")
        self.frame_rate_label, self.frame_rate_info = _field_header("Frame Rate")
        self.quality_label, self.quality_info = _field_header("Video Quality")
        self.encoding_label, self.encoding_info = _field_header("Encoding Speed")
        self.audio_bitrate_label, self.audio_bitrate_info = _field_header("Audio Bitrate")

        fields = QGridLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(10)
        fields.addWidget(self.resolution_label, 0, 0)
        fields.addWidget(self.frame_rate_label, 0, 1)
        fields.addWidget(self.resolution_combo, 1, 0)
        fields.addWidget(self.frame_rate_combo, 1, 1)
        fields.addWidget(self.quality_label, 2, 0)
        fields.addWidget(self.encoding_label, 2, 1)
        fields.addWidget(self.quality_combo, 3, 0)
        fields.addWidget(self.encoding_combo, 3, 1)
        fields.addWidget(self.audio_bitrate_label, 4, 0)
        fields.addWidget(self.audio_bitrate_combo, 5, 0)
        fields.setColumnStretch(0, 1)
        fields.setColumnStretch(1, 1)

        self.action_footer = ExportActionFooter("Export")
        self.action_footer.triggered.connect(self.triggered.emit)
        # Compatibility aliases keep the worker/action contract shared with existing callers.
        self.button = self.action_footer.button
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
            self.resolution_combo,
            self.frame_rate_combo,
            self.quality_combo,
            self.encoding_combo,
            self.audio_bitrate_combo,
        ):
            combo.currentIndexChanged.connect(self._on_detail_changed)

        self.apply_language()
        self._apply_settings(video_export_preset(PRESET_YOUTUBE_1080P))

    def settings(self) -> VideoExportSettings:
        resolution = str(self.resolution_combo.currentData() or "1920x1080")
        width, height = (int(value) for value in resolution.split("x", 1))
        preset_id = self._selected_preset_id()
        return VideoExportSettings(
            preset_id=preset_id,
            width=int(width),
            height=int(height),
            frame_rate=int(self.frame_rate_combo.currentData() or 30),
            quality_crf=int(self.quality_combo.currentData() or 18),
            encoding_preset=str(self.encoding_combo.currentData() or ENCODING_STANDARD),
            audio_bitrate_kbps=int(self.audio_bitrate_combo.currentData() or 320),
            target_size_bytes=(
                VIDEO_TARGET_10MB_BYTES
                if preset_id == PRESET_DISCORD_10MB
                else None
            ),
        )

    def select_preset(self, preset_id: str) -> None:
        if preset_id not in self.preset_buttons:
            raise ValueError(f"Unknown video export preset: {preset_id}")
        self._apply_settings(video_export_preset(preset_id))

    def set_action_enabled(self, is_enabled: bool) -> None:
        self.action_footer.set_action_enabled(is_enabled)

    def set_running(self, is_running: bool) -> None:
        self._running = is_running
        for button in self.preset_buttons.values():
            button.setEnabled(not is_running)
        self._sync_detail_controls()
        self.action_footer.set_running(is_running)

    def set_progress(self, value: int) -> None:
        self.action_footer.set_progress(value)

    def set_status(self, text: str) -> None:
        self.action_footer.set_status(text)

    def apply_language(self) -> None:
        selected = {
            "resolution": self.resolution_combo.currentData(),
            "frame_rate": self.frame_rate_combo.currentData(),
            "quality": self.quality_combo.currentData(),
            "encoding": self.encoding_combo.currentData(),
            "audio_bitrate": self.audio_bitrate_combo.currentData(),
        }
        self._updating = True
        for button in self.preset_buttons.values():
            apply_widget_language(button)
        _set_combo_items(
            self.resolution_combo,
            (
                ("1080p (1920 x 1080)", "1920x1080"),
                ("720p (1280 x 720)", "1280x720"),
                ("480p (854 x 480)", "854x480"),
                ("360p (640 x 360)", "640x360"),
            ),
            selected["resolution"] or "1920x1080",
        )
        _set_combo_items(
            self.frame_rate_combo,
            tuple((f"{value} fps", value) for value in (24, 30, 60)),
            selected["frame_rate"] or 30,
        )
        _set_combo_items(
            self.quality_combo,
            (("Maximum", 16), ("High", 18), ("Balanced", 21), ("Smaller File", 24)),
            selected["quality"] or 18,
        )
        _set_combo_items(
            self.encoding_combo,
            (("Fast", ENCODING_FAST), ("Standard", ENCODING_STANDARD), ("Slow", ENCODING_SLOW)),
            selected["encoding"] or ENCODING_STANDARD,
        )
        _set_combo_items(
            self.audio_bitrate_combo,
            tuple(
                (f"AAC {value} kbps", value)
                for value in (64, 96, 128, 192, 256, 320)
            ),
            selected["audio_bitrate"] or 320,
        )
        self._updating = False
        apply_widget_language(self)
        self._apply_help_text()
        self._update_summary()
        self._sync_detail_controls()

    def _select_preset_from_button(self, preset_id: str) -> None:
        if preset_id == PRESET_CUSTOM:
            self._update_summary()
            self.settings_changed.emit(self.settings())
            return
        self._apply_settings(video_export_preset(preset_id))

    def _on_detail_changed(self) -> None:
        if self._updating:
            return
        self._updating = True
        self.preset_buttons[PRESET_CUSTOM].setChecked(True)
        self._updating = False
        self._update_summary()
        self._sync_detail_controls()
        self.settings_changed.emit(self.settings())

    def _apply_settings(self, settings: VideoExportSettings) -> None:
        self._updating = True
        self.preset_buttons[settings.preset_id].setChecked(True)
        _select_data(self.resolution_combo, settings.resolution_label)
        _select_data(self.frame_rate_combo, settings.frame_rate)
        _select_data(self.quality_combo, settings.quality_crf)
        _select_data(self.encoding_combo, settings.encoding_preset)
        _select_data(self.audio_bitrate_combo, settings.audio_bitrate_kbps)
        self._updating = False
        self._update_summary()
        self._sync_detail_controls()
        self.settings_changed.emit(self.settings())

    def _update_summary(self) -> None:
        settings = self.settings()
        if settings.target_size_bytes is not None:
            self.summary_label.setText(
                tr("MP4 / H.264 / Content-adaptive resolution / VMAF / Two-pass / Under 10 MB")
            )
            return
        self.summary_label.setText(
            f"MP4 / H.264 / {settings.width} x {settings.height} / "
            f"{settings.frame_rate} fps / AAC {settings.audio_bitrate_kbps} kbps"
        )

    def _apply_help_text(self) -> None:
        self.resolution_info.set_content(
            tr("Resolution"),
            tr("1080p is recommended for final videos. 720p renders faster and uses less storage."),
        )
        self.frame_rate_info.set_content(
            tr("Frame Rate"),
            tr("30 fps suits most music videos. Use 60 fps only when the source is high frame rate."),
        )
        self.quality_info.set_content(
            tr("Video Quality"),
            tr(
                "Higher quality preserves more detail but increases render time and file size. "
                "The 10MB preset compares representative sections and selects the highest-scoring resolution."
            ),
        )
        self.encoding_info.set_content(
            tr("Encoding Speed"),
            tr("Slower encoding can reduce file size at the same visual quality."),
        )
        self.audio_bitrate_info.set_content(
            tr("Audio Bitrate"),
            tr("320 kbps is recommended when the audio mix is the main result."),
        )

    def _selected_preset_id(self) -> str:
        return next(
            (preset_id for preset_id, button in self.preset_buttons.items() if button.isChecked()),
            PRESET_YOUTUBE_1080P,
        )

    def _sync_detail_controls(self) -> None:
        automatic = self._selected_preset_id() == PRESET_DISCORD_10MB
        for combo in (
            self.resolution_combo,
            self.frame_rate_combo,
            self.quality_combo,
            self.encoding_combo,
            self.audio_bitrate_combo,
        ):
            combo.setEnabled(not self._running and not automatic)


def _setting_combo() -> ScrollSafeComboBox:
    combo = ScrollSafeComboBox()
    combo.setObjectName("ExportSettingCombo")
    return combo


def _field_header(text: str) -> tuple[QFrame, InfoPopoverButton]:
    header = QFrame()
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


def _set_combo_items(
    combo: ScrollSafeComboBox,
    items: tuple[tuple[str, object], ...],
    selected: object,
) -> None:
    combo.blockSignals(True)
    combo.clear()
    for label, value in items:
        combo.addItem(tr(label), value)
    _select_data(combo, selected)
    combo.blockSignals(False)


def _select_data(combo: ScrollSafeComboBox, value: object) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
