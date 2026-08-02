from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from jang_app.qt_app.localization import apply_widget_language, set_translated_tooltip
from jang_app.qt_app.widgets import SvgIconButton, ValueSlider
from jang_app.services.studio_session import StudioMasterState


class StudioMasterPanel(QFrame):
    processing_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._loading = False

        title = QLabel("Master")
        title.setObjectName("SectionTitle")
        self.reset_button = SvgIconButton("refresh", size=30)
        self.reset_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.reset_button, "Reset master processing")
        self.reset_button.clicked.connect(lambda: self.set_state(StudioMasterState(), emit=True))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title, 1)
        header.addWidget(self.reset_button, 0)

        self.gain_slider = ValueSlider(unity_value=0, width=190, object_name="MasterValueSlider")
        self.gain_slider.setRange(-24, 12)
        self.gain_slider.valueChanged.connect(self._on_value_changed)
        self.gain_value = _value_label()

        self.width_slider = ValueSlider(unity_value=100, width=190, object_name="MasterValueSlider")
        self.width_slider.setRange(0, 200)
        self.width_slider.valueChanged.connect(self._on_value_changed)
        self.width_value = _value_label()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(_control_row("Gain", self.gain_slider, self.gain_value))
        layout.addLayout(_control_row("Stereo Width", self.width_slider, self.width_value))
        self.set_state(StudioMasterState())

    def state(self) -> StudioMasterState:
        return StudioMasterState(
            gain_db=self.gain_slider.value(),
            stereo_width_percent=self.width_slider.value(),
        )

    def set_state(self, state: StudioMasterState, *, emit: bool = False) -> None:
        self._loading = True
        self.gain_slider.setValue(max(-24, min(12, state.gain_db)))
        self.width_slider.setValue(max(0, min(200, state.stereo_width_percent)))
        self._loading = False
        self._update_values()
        if emit:
            self.processing_changed.emit(self.state())

    def set_processing_enabled(self, enabled: bool) -> None:
        self.gain_slider.setEnabled(enabled)
        self.width_slider.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.gain_slider.set_theme_mode(theme_mode)
        self.width_slider.set_theme_mode(theme_mode)
        self.reset_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.reset_button, "Reset master processing")

    def _on_value_changed(self, _value: int) -> None:
        self._update_values()
        if not self._loading:
            self.processing_changed.emit(self.state())

    def _update_values(self) -> None:
        gain = self.gain_slider.value()
        self.gain_value.setText(f"{gain:+d} dB")
        self.width_value.setText(f"{self.width_slider.value()}%")


def _control_row(label_text: str, slider: ValueSlider, value_label: QLabel) -> QHBoxLayout:
    label = QLabel(label_text)
    label.setObjectName("StudioMasterLabel")
    label.setFixedWidth(88)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(label, 0)
    row.addWidget(slider, 1)
    row.addWidget(value_label, 0)
    return row


def _value_label() -> QLabel:
    label = QLabel()
    label.setObjectName("StudioMasterValue")
    label.setFixedWidth(54)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label
