from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.collapsible_card_header import CollapsibleCardHeader
from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import (
    FeedbackButton,
    InfoPopoverButton,
    ScrollSafeSlider,
)
from jang_app.services.i18n import tr
from jang_app.services.rvc_inference_settings import (
    PRESET_BALANCED,
    PRESET_CUSTOM,
    PRESET_DETAIL,
    PRESET_TIMBRE,
    RvcInferenceSettings,
    matching_rvc_inference_preset,
    normalize_rvc_inference_settings,
    rvc_inference_preset,
)


class RvcInferenceControls(QFrame):
    settings_changed = Signal(object)

    def __init__(self, settings: RvcInferenceSettings | None = None) -> None:
        super().__init__()
        self.setObjectName("InsetCard")
        self._updating = False

        self.header = CollapsibleCardHeader("Conversion Quality")
        self.header.toggled.connect(self._set_details_expanded)
        self.details_button = self.header.toggle_button

        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.preset_buttons: dict[str, FeedbackButton] = {}
        preset_bar = QFrame()
        preset_bar.setObjectName("ExportPresetBar")
        preset_layout = QHBoxLayout(preset_bar)
        preset_layout.setContentsMargins(4, 4, 4, 4)
        preset_layout.setSpacing(4)
        for preset_id, label in (
            (PRESET_BALANCED, "Balanced"),
            (PRESET_TIMBRE, "Timbre"),
            (PRESET_DETAIL, "Detail"),
        ):
            button = FeedbackButton()
            button.setObjectName("RvcInferencePresetButton")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
            set_translated_text(button, label)
            button.clicked.connect(
                lambda _checked=False, selected=preset_id: self._select_preset(selected)
            )
            self.preset_group.addButton(button)
            self.preset_buttons[preset_id] = button
            preset_layout.addWidget(button, 1)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("SecondaryText")
        self.summary_label.setWordWrap(True)

        self.custom_badge = QLabel()
        self.custom_badge.setObjectName("RvcInferenceCustomBadge")
        set_translated_text(self.custom_badge, "Adjusted")
        self.header.add_status_widget(self.custom_badge)

        self.index_rate_control = _ScaledSlider(0.0, 1.0, decimals=2)
        self.filter_radius_control = _ScaledSlider(0, 7, decimals=0)
        self.rms_mix_rate_control = _ScaledSlider(0.0, 1.0, decimals=2)
        self.protect_control = _ScaledSlider(0.0, 0.5, decimals=2)

        self.index_rate_label, self.index_rate_info = _field_header("Index Influence")
        self.filter_radius_label, self.filter_radius_info = _field_header("Pitch Smoothing")
        self.rms_mix_rate_label, self.rms_mix_rate_info = _field_header("Volume Envelope")
        self.protect_label, self.protect_info = _field_header("Breath Protection")

        self.details_panel = QFrame()
        self.details_panel.setObjectName("RvcInferenceDetailsPanel")
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(0, 4, 0, 0)
        details_layout.setSpacing(7)
        for header, control in (
            (self.index_rate_label, self.index_rate_control),
            (self.filter_radius_label, self.filter_radius_control),
            (self.rms_mix_rate_label, self.rms_mix_rate_control),
            (self.protect_label, self.protect_control),
        ):
            details_layout.addLayout(_field_row(header, control))
        self.details_panel.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 11)
        layout.setSpacing(7)
        layout.addWidget(self.header)
        layout.addWidget(preset_bar)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.details_panel)

        for control in (
            self.index_rate_control,
            self.filter_radius_control,
            self.rms_mix_rate_control,
            self.protect_control,
        ):
            control.value_changed.connect(self._on_value_changed)

        self.set_settings(settings or RvcInferenceSettings(), emit=False)
        self.apply_language()

    def settings(self) -> RvcInferenceSettings:
        return normalize_rvc_inference_settings(
            RvcInferenceSettings(
                index_rate=self.index_rate_control.value(),
                filter_radius=self.filter_radius_control.value(),
                rms_mix_rate=self.rms_mix_rate_control.value(),
                protect=self.protect_control.value(),
            )
        )

    def set_settings(self, settings: RvcInferenceSettings, *, emit: bool = True) -> None:
        normalized = normalize_rvc_inference_settings(settings)
        self._updating = True
        self.index_rate_control.setValue(normalized.index_rate)
        self.filter_radius_control.setValue(normalized.filter_radius)
        self.rms_mix_rate_control.setValue(normalized.rms_mix_rate)
        self.protect_control.setValue(normalized.protect)
        self._set_matching_preset(normalized)
        self._updating = False
        self._update_summary()
        if emit:
            self.settings_changed.emit(normalized)

    def apply_language(self) -> None:
        apply_widget_language(self)
        for button in self.preset_buttons.values():
            apply_widget_language(button)
        self.header.apply_language()
        self.index_rate_info.set_content(
            tr("Index Influence"),
            tr("Higher values use more characteristics from the model index, but can also copy noise or create metallic artifacts."),
            tr("Start at 0.75. Reduce it when pronunciation becomes rough or unstable."),
        )
        self.filter_radius_info.set_content(
            tr("Pitch Smoothing"),
            tr("Smooths short pitch estimation errors. It mainly affects harvested pitch data and may have little effect with RMVPE."),
            tr("3 is a safe reference value."),
        )
        self.rms_mix_rate_info.set_content(
            tr("Volume Envelope"),
            tr("0 follows the source vocal loudness closely. 1 keeps the converted vocal's own loudness movement."),
            tr("0.25 preserves the source performance without forcing it completely."),
        )
        self.protect_info.set_content(
            tr("Breath Protection"),
            tr("Lower values preserve more unvoiced consonants and breath from the source. Too much protection can retain source timbre."),
            tr("0.33 is the standard starting point."),
        )
        self._update_summary()

    def _select_preset(self, preset_id: str) -> None:
        self.set_settings(rvc_inference_preset(preset_id))

    def _on_value_changed(self, *_args) -> None:
        if self._updating:
            return
        self._updating = True
        self._set_matching_preset(self.settings())
        self._updating = False
        self._update_summary()
        self.settings_changed.emit(self.settings())

    def _update_summary(self) -> None:
        preset = matching_rvc_inference_preset(self.settings())
        descriptions = {
            PRESET_BALANCED: "Stable default conversion settings.",
            PRESET_TIMBRE: "Applies the model timbre more strongly.",
            PRESET_DETAIL: "Preserves more consonants and breath.",
            PRESET_CUSTOM: "Uses manually adjusted values.",
        }
        self.summary_label.setText(tr(descriptions[preset]))
        values = self.settings()
        self.header.set_summary(
            f"{values.index_rate:.2f} / {values.filter_radius} / "
            f"{values.rms_mix_rate:.2f} / {values.protect:.2f}"
        )
        self.custom_badge.setVisible(preset == PRESET_CUSTOM)
        if preset == PRESET_CUSTOM:
            self._clear_preset_selection()

    def _set_details_expanded(self, expanded: bool) -> None:
        self.details_panel.setVisible(expanded)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.header.set_theme_mode(theme_mode)

    def _clear_preset_selection(self) -> None:
        self.preset_group.setExclusive(False)
        for button in self.preset_buttons.values():
            button.setChecked(False)
        self.preset_group.setExclusive(True)

    def _set_matching_preset(self, settings: RvcInferenceSettings) -> None:
        preset = matching_rvc_inference_preset(settings)
        if preset == PRESET_CUSTOM:
            self._clear_preset_selection()
            return
        self.preset_buttons[preset].setChecked(True)


class _ScaledSlider(QWidget):
    value_changed = Signal()

    def __init__(
        self,
        minimum: float,
        maximum: float,
        *,
        decimals: int,
    ) -> None:
        super().__init__()
        self._decimals = decimals
        self._scale = 10**decimals

        self.slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("RvcInferenceSlider")
        self.slider.setRange(
            round(minimum * self._scale),
            round(maximum * self._scale),
        )
        self.slider.setSingleStep(1)

        self.value_label = QLabel()
        self.value_label.setObjectName("RvcInferenceSliderValue")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.value_label.setFixedWidth(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label, 0)

        self.slider.valueChanged.connect(self._on_slider_value_changed)
        self._update_value_label()

    def value(self) -> float | int:
        value = self.slider.value() / self._scale
        return round(value, self._decimals) if self._decimals else int(value)

    def setValue(self, value: float | int) -> None:  # noqa: N802
        self.slider.setValue(round(float(value) * self._scale))

    def _on_slider_value_changed(self, _value: int) -> None:
        self._update_value_label()
        self.value_changed.emit()

    def _update_value_label(self) -> None:
        value = self.value()
        self.value_label.setText(
            f"{value:.{self._decimals}f}" if self._decimals else str(value)
        )


def _field_header(text: str) -> tuple[QWidget, InfoPopoverButton]:
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel()
    label.setObjectName("FieldLabel")
    set_translated_text(label, text)
    info = InfoPopoverButton()
    layout.addWidget(label)
    layout.addWidget(info)
    layout.addStretch(1)
    return header, info


def _field_row(header: QWidget, control: QWidget) -> QVBoxLayout:
    row = QVBoxLayout()
    row.setContentsMargins(0, 0, 0, 2)
    row.setSpacing(3)
    header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.addWidget(header)
    row.addWidget(control)
    return row
