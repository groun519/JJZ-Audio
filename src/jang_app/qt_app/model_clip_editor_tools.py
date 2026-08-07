from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import (
    FeedbackButton,
    InfoPopoverButton,
    ScrollSafeSlider,
    ScrollSafeSpinBox,
    SurfaceFrame,
    SvgIconButton,
    TransparentContainer,
)
from jang_app.services.i18n import tr


_CONTROL_SIZE = 30
_INSPECTOR_WIDTH = 320


class DenoiseToolPanel(QFrame):
    capture_sample_requested = Signal()
    clear_sample_requested = Signal()
    preview_requested = Signal()
    apply_requested = Signal()
    remove_requested = Signal()
    source_requested = Signal(str)
    reference_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DatasetToolPanel")
        self._has_sample = False
        self._has_result = False
        self._has_temporary_preview = False
        self._selection_start_ms = 0
        self._selection_end_ms = 0
        self._sample_start_ms = 0
        self._sample_end_ms = 0
        self._available = False
        self._has_selection = False
        self._reference_mode = "automatic"

        self.automatic_reference_button = FeedbackButton("Automatic Analysis")
        self.selection_reference_button = FeedbackButton("Selected Range")
        self.reference_button_group = QButtonGroup(self)
        self.reference_button_group.setExclusive(True)
        self.reference_control = QFrame()
        self.reference_control.setObjectName("DatasetResultTabs")
        reference_layout = QHBoxLayout(self.reference_control)
        reference_layout.setContentsMargins(2, 2, 2, 2)
        reference_layout.setSpacing(0)
        for index, button in enumerate(
            (self.automatic_reference_button, self.selection_reference_button)
        ):
            button.setObjectName("DatasetResultTab")
            button.setCheckable(True)
            self.reference_button_group.addButton(button, index)
            reference_layout.addWidget(button)
        self.automatic_reference_button.clicked.connect(
            lambda: self._choose_reference_mode("automatic")
        )
        self.selection_reference_button.clicked.connect(
            lambda: self._choose_reference_mode("selection")
        )

        self.sample_status_label = QLabel("No range selected")
        self.sample_status_label.setObjectName("DatasetToolValue")
        self.sample_hint_label = QLabel("Select noise-only audio in the waveform for a cleaner result.")
        self.sample_hint_label.setObjectName("DatasetToolHint")
        self.sample_hint_label.setWordWrap(True)
        self.sample_button = FeedbackButton("Use Current Selection")
        self.sample_button.setObjectName("DatasetEditorSecondaryButton")
        self.sample_button.clicked.connect(self.capture_sample_requested.emit)
        self.clear_sample_button = _icon_button("close", "Clear noise sample", 26)
        self.clear_sample_button.clicked.connect(self.clear_sample_requested.emit)

        sample_value_row = QHBoxLayout()
        sample_value_row.setContentsMargins(0, 0, 0, 0)
        sample_value_row.setSpacing(4)
        sample_value_row.addWidget(self.sample_status_label, 1)
        sample_value_row.addWidget(self.clear_sample_button)
        sample_action_row = QHBoxLayout()
        sample_action_row.setContentsMargins(0, 0, 0, 0)
        sample_action_row.setSpacing(8)
        sample_action_row.addWidget(self.sample_button)
        sample_action_row.addWidget(self.sample_hint_label, 1)
        self.sample_detail = TransparentContainer()
        sample_detail_layout = QVBoxLayout(self.sample_detail)
        sample_detail_layout.setContentsMargins(0, 0, 0, 0)
        sample_detail_layout.setSpacing(6)
        sample_detail_layout.addLayout(sample_value_row)
        sample_detail_layout.addLayout(sample_action_row)
        self.sample_section = _tool_section(
            "NOISE REFERENCE",
            self.reference_control,
            self.sample_detail,
        )

        self.strength_slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setObjectName("DatasetDenoiseSlider")
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(50)
        self.strength_value_label = QLabel("50%")
        self.strength_value_label.setObjectName("DatasetToolValue")
        self.strength_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.strength_value_label.setFixedWidth(38)
        self.strength_slider.valueChanged.connect(
            lambda value: self.strength_value_label.setText(f"{value}%")
        )
        strength_row = QHBoxLayout()
        strength_row.setContentsMargins(0, 0, 0, 0)
        strength_row.setSpacing(8)
        strength_row.addWidget(self.strength_slider, 1)
        strength_row.addWidget(self.strength_value_label)
        strength_scale = QHBoxLayout()
        strength_scale.setContentsMargins(0, 0, 0, 0)
        preserve_label = QLabel("Preserve voice")
        preserve_label.setObjectName("DatasetToolHint")
        stronger_label = QLabel("Stronger")
        stronger_label.setObjectName("DatasetToolHint")
        strength_scale.addWidget(preserve_label)
        strength_scale.addStretch(1)
        strength_scale.addWidget(stronger_label)
        self.strength_section = _tool_section("REDUCTION", strength_row, strength_scale)

        self.preview_button = FeedbackButton("Preview Selection")
        self.preview_button.setObjectName("DatasetEditorSecondaryButton")
        self.preview_button.clicked.connect(self.preview_requested.emit)
        self.apply_button = FeedbackButton("Apply to Audio")
        self.apply_button.setObjectName("DatasetEditorPrimaryButton")
        self.apply_button.clicked.connect(self.apply_requested.emit)

        self.result_control = QFrame()
        self.result_control.setObjectName("DatasetResultTabs")
        source_layout = QHBoxLayout(self.result_control)
        source_layout.setContentsMargins(2, 2, 2, 2)
        source_layout.setSpacing(0)
        self.original_button = FeedbackButton("Original")
        self.processed_button = FeedbackButton("Processed")
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        for index, button in enumerate((self.original_button, self.processed_button)):
            button.setObjectName("DatasetResultTab")
            button.setCheckable(True)
            self.source_button_group.addButton(button, index)
            source_layout.addWidget(button)
        self.original_button.setChecked(True)
        self.original_button.clicked.connect(lambda: self.source_requested.emit("original"))
        self.processed_button.clicked.connect(lambda: self.source_requested.emit("denoised"))

        self.restore_button = FeedbackButton("Restore Original")
        self.restore_button.setObjectName("DatasetEditorSecondaryButton")
        self.restore_button.clicked.connect(self.remove_requested.emit)
        self.safety_label = QLabel("Original preserved | Revert anytime")
        self.safety_label.setObjectName("DatasetToolHint")
        self.safety_label.setWordWrap(True)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.preview_button)
        action_row.addWidget(self.apply_button)
        result_row = QHBoxLayout()
        result_row.setContentsMargins(0, 0, 0, 0)
        result_row.setSpacing(6)
        result_row.addWidget(self.result_control, 1)
        result_row.addWidget(self.restore_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DatasetToolProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("DatasetToolValue")
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)
        self.progress_widget = TransparentContainer()
        self.progress_widget.setLayout(progress_row)
        self.progress_widget.hide()

        self.action_section = _tool_section(
            "PROCESS",
            self.safety_label,
            action_row,
            result_row,
            self.progress_widget,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(self.sample_section)
        layout.addWidget(_horizontal_divider())
        layout.addWidget(self.strength_section)
        layout.addWidget(_horizontal_divider())
        layout.addWidget(self.action_section)
        layout.addStretch(1)
        self.set_reference_mode("automatic")
        self.set_state(False, False, False, False, "original")

    def set_state(
        self,
        available: bool,
        has_selection: bool,
        has_sample: bool,
        has_result: bool,
        source: str,
        *,
        has_temporary_preview: bool = False,
    ) -> None:
        self._available = available
        self._has_selection = has_selection
        self._has_sample = has_sample
        self._has_result = has_result
        self._has_temporary_preview = has_temporary_preview
        processed_available = has_result or has_temporary_preview
        self.strength_slider.setEnabled(available)
        self.original_button.setEnabled(available)
        self.processed_button.setEnabled(available and processed_available)
        self.result_control.setVisible(processed_available)
        self.restore_button.setEnabled(available and has_result)
        self.restore_button.setVisible(has_result)
        set_translated_text(self.apply_button, "Update Result" if has_result else "Apply to Audio")
        self.original_button.setChecked(source == "original")
        self.processed_button.setChecked(source == "denoised" and processed_available)
        if source == "denoised" and not processed_available:
            self.original_button.setChecked(True)
        self._refresh_sample_text()
        self._sync_reference_controls()

    def set_selection(self, start_ms: int, end_ms: int) -> None:
        self._selection_start_ms = max(0, start_ms)
        self._selection_end_ms = max(self._selection_start_ms, end_ms)
        self._refresh_sample_text()
        self._sync_reference_controls()

    def set_noise_sample(self, start_ms: int, end_ms: int) -> None:
        self._sample_start_ms = max(0, start_ms)
        self._sample_end_ms = max(self._sample_start_ms, end_ms)
        self._has_sample = self._sample_end_ms - self._sample_start_ms >= 100
        self.set_reference_mode("selection" if self._has_sample else "automatic")
        self._refresh_sample_text()

    def reference_mode(self) -> str:
        return self._reference_mode

    def set_reference_mode(self, mode: str) -> None:
        self._reference_mode = "selection" if mode == "selection" else "automatic"
        self.automatic_reference_button.setChecked(self._reference_mode == "automatic")
        self.selection_reference_button.setChecked(self._reference_mode == "selection")
        self.sample_detail.setVisible(self._reference_mode == "selection")
        self._refresh_sample_text()
        self._sync_reference_controls()

    def set_processing(self, is_processing: bool, progress: int = 0) -> None:
        self.progress_widget.setVisible(is_processing)
        self.preview_button.setVisible(not is_processing)
        self.apply_button.setVisible(not is_processing)
        self.result_control.setVisible(
            not is_processing and (self._has_result or self._has_temporary_preview)
        )
        self.restore_button.setVisible(not is_processing and self._has_result)
        if is_processing:
            self.set_progress(progress)

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_label.setText(f"{progress}%")

    def apply_language(self) -> None:
        set_translated_text(self.automatic_reference_button, "Automatic Analysis")
        set_translated_text(self.selection_reference_button, "Selected Range")
        set_translated_text(self.sample_button, "Use Current Selection")
        set_translated_text(self.preview_button, "Preview Selection")
        set_translated_text(self.original_button, "Original")
        set_translated_text(self.processed_button, "Processed")
        set_translated_text(self.restore_button, "Restore Original")
        set_translated_text(self.safety_label, "Original preserved | Revert anytime")
        set_translated_tooltip(self.clear_sample_button, "Clear noise sample")
        self._refresh_sample_text()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.clear_sample_button.set_theme_mode(theme_mode)

    def _refresh_sample_text(self) -> None:
        if self._has_sample:
            self.sample_status_label.setText(
                f"{_format_time(self._sample_start_ms)} - {_format_time(self._sample_end_ms)}"
            )
            set_translated_text(self.sample_hint_label, "Noise sample captured")
            set_translated_text(self.sample_button, "Replace with Current Selection")
            return
        selection_duration = self._selection_end_ms - self._selection_start_ms
        set_translated_text(self.sample_status_label, "No range selected")
        if 0 < selection_duration < 500:
            set_translated_text(self.sample_hint_label, "Select at least 0.5 seconds of noise.")
        else:
            set_translated_text(
                self.sample_hint_label,
                "Select noise-only audio in the waveform for a cleaner result.",
            )
        set_translated_text(self.sample_button, "Use Current Selection")

    def _choose_reference_mode(self, mode: str) -> None:
        self.set_reference_mode(mode)
        self.reference_mode_changed.emit(self._reference_mode)

    def _sync_reference_controls(self) -> None:
        using_selection = self._reference_mode == "selection"
        sample_selection_available = self._selection_end_ms - self._selection_start_ms >= 500
        reference_ready = not using_selection or self._has_sample
        self.automatic_reference_button.setEnabled(self._available)
        self.selection_reference_button.setEnabled(self._available)
        self.sample_button.setEnabled(
            self._available and using_selection and sample_selection_available
        )
        self.clear_sample_button.setEnabled(self._available and using_selection and self._has_sample)
        self.clear_sample_button.setVisible(using_selection and self._has_sample)
        self.preview_button.setEnabled(
            self._available and self._has_selection and reference_ready
        )
        self.apply_button.setEnabled(self._available and reference_ready)


class RegionDetectionToolPanel(QFrame):
    analyze_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DatasetToolPanel")
        self._result_count = 0
        self._result_stale = False

        self.threshold_spin = _analysis_spin(-80, -10, -40, " dB", 1)
        self.silence_spin = _analysis_spin(100, 5000, 500, " ms", 100)
        self.padding_spin = _analysis_spin(0, 1000, 120, " ms", 20)
        self.max_clip_spin = _analysis_spin(3, 30, 12, " s", 1)

        self.threshold_info = InfoPopoverButton()
        self.silence_info = InfoPopoverButton()
        self.padding_info = InfoPopoverButton()
        self.max_clip_info = InfoPopoverButton()

        detection_row = _labeled_controls(
            (
                ("Silence level", self.threshold_spin, self.threshold_info),
                ("Minimum silence", self.silence_spin, self.silence_info),
            )
        )
        shaping_row = _labeled_controls(
            (
                ("Edge padding", self.padding_spin, self.padding_info),
                ("Maximum clip", self.max_clip_spin, self.max_clip_info),
            )
        )
        self.detection_section = _tool_section("DETECTION", detection_row)
        self.shaping_section = _tool_section("CLIP SHAPING", shaping_row)

        self.analyze_button = FeedbackButton("Analyze Regions")
        self.analyze_button.setObjectName("DatasetEditorPrimaryButton")
        self.analyze_button.clicked.connect(self.analyze_requested.emit)
        self.result_label = QLabel("Not analyzed")
        self.result_label.setObjectName("DatasetToolHint")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.analyze_button)
        action_row.addWidget(self.result_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DatasetToolProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("DatasetToolValue")
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)
        self.progress_widget = TransparentContainer()
        self.progress_widget.setLayout(progress_row)
        self.progress_widget.hide()
        self.action_section = _tool_section("RUN", action_row, self.progress_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(self.detection_section)
        layout.addWidget(_horizontal_divider())
        layout.addWidget(self.shaping_section)
        layout.addWidget(_horizontal_divider())
        layout.addWidget(self.action_section)
        layout.addStretch(1)
        self._sync_info_popovers()

    def parameters(self) -> tuple[int, int, int, int]:
        return (
            self.threshold_spin.value(),
            self.silence_spin.value(),
            self.padding_spin.value(),
            self.max_clip_spin.value(),
        )

    def set_available(self, available: bool) -> None:
        for control in (
            self.threshold_spin,
            self.silence_spin,
            self.padding_spin,
            self.max_clip_spin,
            self.analyze_button,
        ):
            control.setEnabled(available)

    def set_result(self, count: int, *, stale: bool = False) -> None:
        self._result_count = max(0, count)
        self._result_stale = stale and self._result_count > 0
        self._refresh_result_text()

    def set_processing(self, is_processing: bool, progress: int = 0) -> None:
        self.analyze_button.setVisible(not is_processing)
        self.result_label.setVisible(not is_processing)
        self.progress_widget.setVisible(is_processing)
        if is_processing:
            self.set_progress(progress)

    def set_progress(self, value: int) -> None:
        progress = max(0, min(100, int(value)))
        self.progress_bar.setValue(progress)
        self.progress_label.setText(f"{progress}%")

    def apply_language(self) -> None:
        set_translated_text(self.analyze_button, "Analyze Regions")
        self._refresh_result_text()
        self._sync_info_popovers()

    def _refresh_result_text(self) -> None:
        if self._result_stale:
            set_translated_text(self.result_label, "Reanalysis recommended")
        elif self._result_count:
            set_translated_text(
                self.result_label,
                "{count} regions found",
                count=self._result_count,
            )
        else:
            set_translated_text(self.result_label, "Not analyzed")

    def _sync_info_popovers(self) -> None:
        self.threshold_info.set_content(
            tr("Silence level"),
            tr(
                "Audio quieter than this level is treated as silence. A higher value can "
                "remove quiet speech; a lower value keeps more breath and background noise."
            ),
            tr("Recommended starting point: -40 dB"),
        )
        self.silence_info.set_content(
            tr("Minimum silence"),
            tr(
                "Silence must last this long before a split is created. Shorter values make "
                "more clips; longer values keep phrases together."
            ),
            tr("Recommended starting point: 500 ms"),
        )
        self.padding_info.set_content(
            tr("Edge padding"),
            tr(
                "Keeps extra audio before and after each detected voice region. Too little can "
                "cut consonants; too much keeps unnecessary silence."
            ),
            tr("Recommended starting point: 120 ms"),
        )
        self.max_clip_info.set_content(
            tr("Maximum clip"),
            tr(
                "Voice regions longer than this are divided into smaller training clips. "
                "Shorter clips are easier to review; longer clips preserve more context."
            ),
            tr("Recommended starting point: 12 s"),
        )


class AudioToolInspector(SurfaceFrame):
    def __init__(
        self,
        cleanup_page: DenoiseToolPanel,
        analysis_page: RegionDetectionToolPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("surface", parent)
        self.setObjectName("DatasetAudioInspector")
        self.setFixedWidth(_INSPECTOR_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.cleanup_button = FeedbackButton("Noise Cleanup")
        self.analysis_button = FeedbackButton("Find Clips")
        for index, button in enumerate((self.cleanup_button, self.analysis_button)):
            button.setObjectName("DatasetInspectorTab")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda _checked=False, page=index: self.select_page(page))
        self.cleanup_button.setChecked(True)

        tabs = QFrame()
        tabs.setObjectName("DatasetInspectorTabs")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(2, 2, 2, 2)
        tabs_layout.setSpacing(0)
        tabs_layout.addWidget(self.cleanup_button)
        tabs_layout.addWidget(self.analysis_button)

        header = TransparentContainer(object_name="DatasetInspectorHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 10)
        header_layout.setSpacing(8)
        title = QLabel("AUDIO TOOLS")
        title.setObjectName("DatasetInspectorTitle")
        header_layout.addWidget(title)
        header_layout.addWidget(tabs)

        self.stack = QStackedWidget()
        self.stack.setObjectName("DatasetInspectorStack")
        self.stack.addWidget(cleanup_page)
        self.stack.addWidget(analysis_page)

        self.content = QFrame()
        self.content.setObjectName("DatasetInspectorContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.stack, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.content, 1)

    def select_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def set_theme_mode(self, theme_mode: str) -> None:
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if hasattr(page, "set_theme_mode"):
                page.set_theme_mode(theme_mode)


def _tool_section(title: str, *rows) -> QFrame:
    section = QFrame()
    section.setObjectName("DatasetToolSection")
    title_label = QLabel(title)
    title_label.setObjectName("DatasetToolSectionLabel")
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(title_label)
    for row in rows:
        if isinstance(row, QWidget):
            layout.addWidget(row)
        else:
            layout.addLayout(row)
    return section


def _labeled_controls(
    items: tuple[tuple[str, QWidget, InfoPopoverButton], ...],
) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    for text, control, info_button in items:
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(3)
        label = QLabel(text)
        label.setObjectName("DatasetToolHint")
        header = TransparentContainer(object_name="DatasetToolFieldHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)
        header_layout.addWidget(label)
        header_layout.addWidget(info_button)
        header_layout.addStretch(1)
        group.addWidget(header)
        group.addWidget(control)
        layout.addLayout(group, 1)
    return layout


def _analysis_spin(
    minimum: int,
    maximum: int,
    value: int,
    suffix: str,
    step: int,
) -> ScrollSafeSpinBox:
    spin = ScrollSafeSpinBox()
    spin.setObjectName("DatasetAnalysisSpin")
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setSingleStep(step)
    spin.setFixedHeight(_CONTROL_SIZE)
    return spin


def _icon_button(icon: str, tooltip: str, size: int = 30) -> SvgIconButton:
    button = SvgIconButton(icon, size=size)
    button.setObjectName("DatasetEditorIconButton")
    set_translated_tooltip(button, tooltip)
    return button


def _horizontal_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("DatasetToolDivider")
    divider.setFixedHeight(1)
    return divider


def _format_time(milliseconds: int) -> str:
    total_tenths = max(0, milliseconds) // 100
    minutes, tenths = divmod(total_tenths, 600)
    seconds, tenth = divmod(tenths, 10)
    return f"{minutes:02d}:{seconds:02d}.{tenth}"
