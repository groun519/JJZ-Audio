from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.widgets import (
    DangerIconButton,
    InfoPopoverButton,
    ScrollSafeComboBox,
    ScrollSafeDoubleSpinBox,
    ScrollSafeSpinBox,
    ToggleSwitchButton,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_reverb_presets import (
    CUSTOM_REVERB_PRESET,
    STUDIO_REVERB_PRESETS,
    matching_reverb_preset,
    reverb_preset_settings,
)
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


_FIELD_SPECS = {
    "room_height_m": ("Room Height", 1.0, 30.0, 0.1, " m", 1),
    "room_length_m": ("Room Length", 1.0, 30.0, 0.1, " m", 1),
    "room_width_m": ("Room Width", 1.0, 30.0, 0.1, " m", 1),
    "distance_m": ("Distance", 0.0, 30.0, 0.05, " m", 2),
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

_FIELD_HELP = {
    "room_height_m": (
        "Changes the vertical size of the virtual room. Higher values make the reflections feel taller and more open.",
        "Use 2-4 m for a close vocal. Values above 8 m create a more open space.",
    ),
    "room_length_m": (
        "Changes how far the virtual room extends from front to back. Higher values spread reflections farther apart.",
        "Use 4-8 m for a natural room. Larger values feel more spacious.",
    ),
    "room_width_m": (
        "Changes the side-to-side size of the virtual room. Higher values make the reverb feel wider in stereo.",
        "Use 4-8 m for a natural width. Raise it when the vocal feels too narrow.",
    ),
    "distance_m": (
        "Sets how far the singer seems from the listener. Higher values push the voice deeper into the room.",
        "Use 1-3 m for a clear lead vocal. Raise it when you want the voice farther back.",
    ),
    "pre_delay_ms": (
        "Sets the gap between the original voice and the first reverb. More delay keeps the words clear before the reverb begins.",
        "Start around 15-50 ms for vocals. Negative values make the reflection begin earlier.",
    ),
    "decay_ms": (
        "Sets how long the reverb remains after the sound stops. Higher values create a longer tail.",
        "Use 700-1800 ms for most vocals. Values above 2500 ms create a dreamy tail.",
    ),
    "brightness_percent": (
        "Changes the tone of the reverb. Lower values sound darker and softer; higher values sound brighter and sharper.",
        "Start around 40-65%. Lower it when sibilance becomes harsh.",
    ),
    "modulation_percent": (
        "Adds gentle movement to the reverb. Higher values sound wider and dreamier, but less natural.",
        "Use 0-10% for a natural vocal. Values above 20% create an obvious moving texture.",
    ),
    "early_low_hz": (
        "Chooses which low tones are shaped in the first room reflections. It works together with Low Gain below.",
        "Keep it near 300 Hz unless the first reflections sound boomy or thin.",
    ),
    "early_high_hz": (
        "Chooses which high tones are shaped in the first room reflections. It works together with High Gain below.",
        "Keep it near 10 kHz for a natural starting point.",
    ),
    "early_low_gain_db": (
        "Raises or lowers the low tones in the first room reflections.",
        "Start at 0 dB. Lower it when the first reflections sound boomy; raise it for more body.",
    ),
    "early_high_gain_db": (
        "Raises or lowers the high tones in the first room reflections.",
        "Start at 0 dB. Lower it for softer reflections; raise it for more presence.",
    ),
    "reverb_low_hz": (
        "Chooses which low tones are shaped in the long reverb tail. It works together with Low Gain below.",
        "Keep it near 300 Hz unless the reverb tail sounds boomy or thin.",
    ),
    "reverb_high_hz": (
        "Chooses which high tones are shaped in the long reverb tail. It works together with High Gain below.",
        "Keep it near 10 kHz for a natural starting point.",
    ),
    "reverb_low_gain_db": (
        "Raises or lowers the low tones in the long reverb tail.",
        "Start at 0 dB. Lower it when the tail sounds muddy; raise it for a fuller tail.",
    ),
    "reverb_high_gain_db": (
        "Raises or lowers the high tones in the long reverb tail.",
        "Start at 0 dB. Lower it for a softer tail; raise it for more air and sparkle.",
    ),
    "dry_wet_percent": (
        "Sets how much reverb is mixed with the original sound. 0% is the original only; 100% is the reverb only.",
        "Start around 10-30% for a clear vocal. Use values above 35% for an obvious effect.",
    ),
    "direct_gain_db": (
        "Changes the volume of the original voice inside this effect. 0 dB leaves it unchanged.",
        "Keep it at 0 dB in most cases and adjust the track volume instead.",
    ),
    "early_gain_db": (
        "Changes the volume of the first short reflections that define the room shape.",
        "Start at 0 dB. Lower it for a smoother space; raise it to make the room feel closer.",
    ),
    "reverb_gain_db": (
        "Changes the volume of the long reverb tail without changing the original voice.",
        "Start at 0 dB. Lower it when the tail covers the vocal; raise it for a stronger bloom.",
    ),
}

_PRESET_HELP = (
    "Applies a complete reverb setup with one choice. Each preset changes every control below.",
    "Choose the closest sound first, then fine-tune it. A manual change switches the preset to Custom.",
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
        self.field_info_buttons: dict[str, InfoPopoverButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_action_bar())
        layout.addWidget(self._build_preset_section())
        for title, field_names in _GROUPS:
            layout.addWidget(self._build_section(title, field_names))
        layout.addStretch(1)
        self.apply_language()

    def _build_action_bar(self) -> QFrame:
        action_bar = QFrame()
        action_bar.setObjectName("StudioReverbActionBar")
        self.enabled_button = ToggleSwitchButton()
        self.enabled_button.setChecked(True)
        self.enabled_button.toggled.connect(self._set_effect_enabled)
        self.remove_button = DangerIconButton(size=30)
        self.remove_button.clicked.connect(self._request_remove)
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(10, 6, 10, 6)
        action_layout.setSpacing(8)
        action_layout.addStretch(1)
        action_layout.addWidget(self.enabled_button)
        action_layout.addWidget(self.remove_button)
        return action_bar

    def _build_preset_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioReverbPresetSection")
        self.preset_label = QLabel()
        self.preset_label.setObjectName("StudioInspectorSectionTitle")
        self.preset_info = InfoPopoverButton()
        self.preset_combo = ScrollSafeComboBox()
        self.preset_combo.setObjectName("StudioReverbPresetCombo")
        self.preset_combo.setSizeAdjustPolicy(
            ScrollSafeComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.preset_combo.setMinimumContentsLength(6)
        self.preset_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.preset_combo.currentIndexChanged.connect(self._apply_selected_preset)
        section_layout = QHBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(10)
        section_layout.addWidget(self.preset_label)
        section_layout.addWidget(self.preset_info)
        section_layout.addWidget(self.preset_combo, 1)
        return section

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
            info_button = InfoPopoverButton()
            self.field_info_buttons[field_name] = info_button
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(5)
            label_row.addWidget(label_widget)
            label_row.addWidget(info_button)
            label_row.addStretch(1)
            control = (
                ScrollSafeSpinBox()
                if decimals == 0
                else ScrollSafeDoubleSpinBox()
            )
            control.setObjectName("StudioReverbControl")
            control.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setSuffix(suffix)
            if isinstance(control, ScrollSafeDoubleSpinBox):
                control.setDecimals(decimals)
            control.valueChanged.connect(self._queue_changed)
            control.editingFinished.connect(self._flush_changed)
            self.controls[field_name] = control
            field_layout.addLayout(label_row)
            field_layout.addWidget(control)
            grid.addWidget(field, index // 2, index % 2)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 12, 12, 12)
        section_layout.setSpacing(8)
        section_layout.addWidget(title_label)
        section_layout.addLayout(grid)
        return section

    def apply_language(self) -> None:
        selected_key = self.preset_combo.currentData()
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_label.setText(tr("Preset"))
        self.preset_info.set_content(
            tr("Preset"),
            tr(_PRESET_HELP[0]),
            tr(_PRESET_HELP[1]),
        )
        self.preset_combo.clear()
        for preset in STUDIO_REVERB_PRESETS:
            self.preset_combo.addItem(tr(preset.name), preset.key)
        self.preset_combo.addItem(tr("Custom"), CUSTOM_REVERB_PRESET)
        self._select_preset(selected_key or CUSTOM_REVERB_PRESET)
        del blocker
        self._sync_enabled_button(self.enabled_button.isChecked())
        for title, label in self.group_title_labels.items():
            label.setText(tr(title))
        for field_name, label in self.field_labels.items():
            title = tr(_FIELD_SPECS[field_name][0])
            body, recommendation = _FIELD_HELP[field_name]
            label.setText(title)
            self.field_info_buttons[field_name].set_content(
                title,
                tr(body),
                tr(recommendation),
            )
            self.controls[field_name].setToolTip(
                f"{tr(body)}\n\n{tr(recommendation)}"
            )
        self.remove_button.setToolTip(tr("Remove Effect"))
        self.remove_button.setAccessibleName(tr("Remove Effect"))

    def set_theme_mode(self, theme_mode: str) -> None:
        self.enabled_button.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)

    def set_effect(self, effect: StudioEffect) -> None:
        self._change_timer.stop()
        self._loading = True
        self._effect = effect
        self._set_control_values(effect.reverb)
        self._select_preset(matching_reverb_preset(effect.reverb))
        blocker = QSignalBlocker(self.enabled_button)
        self.enabled_button.setChecked(effect.enabled)
        del blocker
        self._sync_enabled_button(effect.enabled)
        self._loading = False

    def _set_control_values(self, settings: StudioReverbSettings) -> None:
        for field_name, control in self.controls.items():
            control.setValue(getattr(settings, field_name))

    def _select_preset(self, key: str) -> None:
        index = self.preset_combo.findData(key)
        if index < 0:
            index = self.preset_combo.findData(CUSTOM_REVERB_PRESET)
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.setCurrentIndex(index)
        del blocker

    def _apply_selected_preset(self, _index: int) -> None:
        if self._loading:
            return
        settings = reverb_preset_settings(str(self.preset_combo.currentData()))
        if settings is None:
            return
        self._change_timer.stop()
        self._loading = True
        self._set_control_values(settings)
        self._loading = False
        self._emit_changed()

    def _emit_changed(self) -> None:
        if self._loading or self._effect is None:
            return
        self._emit_effect(replace(self._effect, reverb=self._current_settings()))

    def _current_settings(self) -> StudioReverbSettings:
        values = {
            name: control.value()
            for name, control in self.controls.items()
        }
        return StudioReverbSettings(**values)

    def _emit_effect(self, effect: StudioEffect) -> None:
        self._effect = effect
        self.effect_changed.emit(effect)

    def _set_effect_enabled(self, enabled: bool) -> None:
        self._sync_enabled_button(enabled)
        if self._loading or self._effect is None:
            return
        self._change_timer.stop()
        self._emit_effect(
            replace(
                self._effect,
                enabled=enabled,
                reverb=self._current_settings(),
            )
        )

    def _sync_enabled_button(self, enabled: bool) -> None:
        self.enabled_button.setToolTip(tr("Enable or bypass this effect"))
        self.enabled_button.setAccessibleName(
            tr("Effect enabled") if enabled else tr("Effect bypassed")
        )

    def _queue_changed(self, _value: int | float) -> None:
        if not self._loading:
            self._select_preset(CUSTOM_REVERB_PRESET)
            self._change_timer.start()

    def _flush_changed(self) -> None:
        if self._loading:
            return
        self._change_timer.stop()
        self._emit_changed()

    def _request_remove(self) -> None:
        if self._effect is not None:
            self.remove_requested.emit(self._effect.effect_id)
