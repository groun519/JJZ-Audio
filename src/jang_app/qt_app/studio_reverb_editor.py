from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.widgets import (
    FeedbackButton,
    ScrollSafeDoubleSpinBox,
    ScrollSafeSpinBox,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


_FIELD_SPECS = {
    "room_height_m": ("Room Height", 1.0, 30.0, 0.1, " m", 1),
    "room_length_m": ("Room Length", 1.0, 30.0, 0.1, " m", 1),
    "room_width_m": ("Room Width", 1.0, 30.0, 0.1, " m", 1),
    "distance_m": ("Distance", 0.0, 30.0, 0.1, " m", 1),
    "pre_delay_ms": ("Pre-Delay", -200, 200, 1, " ms", 0),
    "decay_ms": ("Reverb Time", 100, 4_000, 10, " ms", 0),
    "brightness_percent": ("Brightness", 0, 100, 1, "%", 0),
    "modulation_percent": ("Modulation", 0, 100, 1, "%", 0),
    "early_low_hz": ("Low Frequency", 50, 500, 10, " Hz", 0),
    "early_high_hz": ("High Frequency", 1_000, 16_000, 100, " Hz", 0),
    "early_low_gain_db": ("Low Gain", -18.0, 6.0, 0.5, " dB", 1),
    "early_high_gain_db": ("High Gain", -18.0, 6.0, 0.5, " dB", 1),
    "reverb_low_hz": ("Low Frequency", 50, 500, 10, " Hz", 0),
    "reverb_high_hz": ("High Frequency", 1_000, 16_000, 100, " Hz", 0),
    "reverb_low_gain_db": ("Low Gain", -18.0, 6.0, 0.5, " dB", 1),
    "reverb_high_gain_db": ("High Gain", -18.0, 6.0, 0.5, " dB", 1),
    "dry_wet_percent": ("Dry / Wet", 0, 100, 1, "%", 0),
    "direct_gain_db": ("Direct", -60.0, 6.0, 0.5, " dB", 1),
    "early_gain_db": ("Early Reflections", -60.0, 6.0, 0.5, " dB", 1),
    "reverb_gain_db": ("Reverb", -60.0, 6.0, 0.5, " dB", 1),
}

_GROUPS = (
    ("Room", ("room_height_m", "room_length_m", "room_width_m", "distance_m")),
    ("Time", ("pre_delay_ms", "decay_ms")),
    ("Character", ("brightness_percent", "modulation_percent")),
    (
        "Early Reflection Tone",
        ("early_low_hz", "early_high_hz", "early_low_gain_db", "early_high_gain_db"),
    ),
    (
        "Reverb Tone",
        ("reverb_low_hz", "reverb_high_hz", "reverb_low_gain_db", "reverb_high_gain_db"),
    ),
    ("Output", ("dry_wet_percent", "direct_gain_db", "early_gain_db", "reverb_gain_db")),
)


class StudioReverbEditor(QWidget):
    effect_changed = Signal(object)
    remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StudioReverbEditor")
        self._effect: StudioEffect | None = None
        self._loading = False
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(24)
        self._change_timer.timeout.connect(self._emit_changed)
        self.controls: dict[str, ScrollSafeSpinBox | ScrollSafeDoubleSpinBox] = {}
        self.group_title_labels: dict[str, QLabel] = {}
        self.field_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for title, field_names in _GROUPS:
            layout.addWidget(self._build_section(title, field_names))

        self.remove_button = FeedbackButton(tr("Remove Effect"), self)
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.clicked.connect(self._request_remove)
        layout.addWidget(self.remove_button)
        layout.addStretch(1)
        self.apply_language()

    def _build_section(self, title: str, field_names: tuple[str, ...]) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioReverbSection")
        title_label = QLabel(tr(title))
        title_label.setObjectName("StudioInspectorSectionTitle")
        self.group_title_labels[title] = title_label
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, field_name in enumerate(field_names):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            label, minimum, maximum, step, suffix, decimals = _FIELD_SPECS[field_name]
            label_widget = QLabel(tr(label))
            label_widget.setObjectName("MutedText")
            self.field_labels[field_name] = label_widget
            control = (
                ScrollSafeSpinBox()
                if decimals == 0
                else ScrollSafeDoubleSpinBox()
            )
            control.setObjectName("StudioReverbControl")
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setSuffix(suffix)
            if isinstance(control, ScrollSafeDoubleSpinBox):
                control.setDecimals(decimals)
            control.valueChanged.connect(self._queue_changed)
            control.editingFinished.connect(self._flush_changed)
            control.setToolTip(tr(_field_tooltip(field_name)))
            self.controls[field_name] = control
            field_layout.addWidget(label_widget)
            field_layout.addWidget(control)
            grid.addWidget(field, index // 2, index % 2)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 12, 12, 12)
        section_layout.setSpacing(8)
        section_layout.addWidget(title_label)
        section_layout.addLayout(grid)
        return section

    def apply_language(self) -> None:
        for title, label in self.group_title_labels.items():
            label.setText(tr(title))
        for field_name, label in self.field_labels.items():
            label.setText(tr(_FIELD_SPECS[field_name][0]))
            self.controls[field_name].setToolTip(tr(_field_tooltip(field_name)))
        self.remove_button.setText(tr("Remove Effect"))

    def set_effect(self, effect: StudioEffect) -> None:
        self._loading = True
        self._effect = effect
        for field_name, control in self.controls.items():
            control.setValue(getattr(effect.reverb, field_name))
        self._loading = False

    def _emit_changed(self) -> None:
        if self._loading or self._effect is None:
            return
        values = {
            name: control.value()
            for name, control in self.controls.items()
        }
        settings = StudioReverbSettings(**values)
        self.effect_changed.emit(replace(self._effect, reverb=settings))

    def _queue_changed(self, _value: int | float) -> None:
        if not self._loading:
            self._change_timer.start()

    def _flush_changed(self) -> None:
        if self._loading:
            return
        self._change_timer.stop()
        self._emit_changed()

    def _request_remove(self) -> None:
        if self._effect is not None:
            self.remove_requested.emit(self._effect.effect_id)


def _field_tooltip(field_name: str) -> str:
    return {
        "room_height_m": "Rebuilds reflections and room modes from the virtual room height.",
        "room_length_m": "Rebuilds reflections and room modes from the virtual room length.",
        "room_width_m": "Rebuilds reflections and room modes from the virtual room width.",
        "distance_m": "Changes only the timing, level, and shape of early reflections between source and listener.",
        "pre_delay_ms": "Offsets the first reflection; negative values move it earlier.",
        "decay_ms": "Sets how long the reverb tail remains audible.",
        "brightness_percent": "Controls frequency-dependent decay; lower values shorten high-frequency reverb.",
        "modulation_percent": "Adds randomized low-frequency phase movement to early reflections.",
        "dry_wet_percent": "Balances the original sound and reverb.",
    }.get(field_name, "Shapes the frequency and level of the reverb.")
