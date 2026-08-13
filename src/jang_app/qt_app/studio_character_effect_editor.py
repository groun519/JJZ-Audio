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
    FeedbackButton,
    InfoPopoverButton,
    ScrollSafeComboBox,
    ScrollSafeSpinBox,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_character_fx_presets import (
    EFFECT_PRESETS,
    matching_character_effect_preset,
    studio_effect_name,
)
from jang_app.services.studio_session import (
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DISTORTION,
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_RADIO_FILTER,
    STUDIO_EFFECT_RING_MODULATOR,
    StudioBitcrusherSettings,
    StudioDistortionSettings,
    StudioEffect,
    StudioLevelMatchSettings,
    StudioRadioFilterSettings,
    StudioRingModulatorSettings,
)


_PRESET_NAMES = {
    "telephone": "Telephone",
    "walkie_talkie": "Walkie-Talkie",
    "old_speaker": "Old Speaker",
    "subtle_metal": "Subtle Metal",
    "robot": "Robot",
    "alarm": "Alarm",
    "light_digital": "Light Digital",
    "retro_10bit": "Retro 10-bit",
    "broken_8bit": "Broken 8-bit",
    "warm": "Warm",
    "grit": "Grit",
    "overdrive": "Overdrive",
    "natural": "Natural",
    "balanced": "Balanced",
    "strong": "Strong",
}

_FIELD_SPECS = {
    STUDIO_EFFECT_RADIO_FILTER: (
        ("low_cut_hz", "Low Cut", 20, 4_000, 10, " Hz"),
        ("high_cut_hz", "High Cut", 120, 20_000, 100, " Hz"),
        ("mix_percent", "Mix", 0, 100, 1, "%"),
    ),
    STUDIO_EFFECT_RING_MODULATOR: (
        ("frequency_hz", "Frequency", 1, 2_000, 1, " Hz"),
        ("mix_percent", "Mix", 0, 100, 1, "%"),
    ),
    STUDIO_EFFECT_BITCRUSHER: (
        ("bit_depth", "Bit Depth", 4, 16, 1, " bit"),
        ("sample_rate_hz", "Sample Rate", 2_000, 48_000, 1_000, " Hz"),
        ("mix_percent", "Mix", 0, 100, 1, "%"),
    ),
    STUDIO_EFFECT_DISTORTION: (
        ("drive_percent", "Drive", 0, 100, 1, "%"),
        ("mix_percent", "Mix", 0, 100, 1, "%"),
    ),
    STUDIO_EFFECT_LEVEL_MATCH: (
        ("strength_percent", "Match Strength", 0, 100, 1, "%"),
        ("response_ms", "Response", 40, 1_000, 10, " ms"),
        ("max_correction_db", "Maximum Correction", 1, 12, 1, " dB"),
        ("silence_threshold_db", "Silence Protection", -80, -30, 1, " dB"),
    ),
}

_FIELD_HELP = {
    "low_cut_hz": "Removes frequencies below this point to make the voice thinner.",
    "high_cut_hz": "Removes frequencies above this point to create a narrow speaker tone.",
    "frequency_hz": "Sets the metallic pulse speed. Higher values sound sharper and more synthetic.",
    "bit_depth": "Lower values reduce level detail and create stronger digital stepping.",
    "sample_rate_hz": "Lower values remove time detail and make the voice rougher.",
    "drive_percent": "Raises saturation strength before the output is level-matched.",
    "mix_percent": "Balances the original voice and the processed voice.",
    "strength_percent": "Sets how closely the processed vocal follows the original vocal volume.",
    "response_ms": "Controls how quickly the correction follows changes in vocal volume.",
    "max_correction_db": "Limits how far the effect may raise or lower the vocal.",
    "silence_threshold_db": "Prevents quiet noise from being amplified when either vocal is silent.",
}

_SETTINGS_TYPES = {
    STUDIO_EFFECT_RADIO_FILTER: ("radio_filter", StudioRadioFilterSettings),
    STUDIO_EFFECT_RING_MODULATOR: ("ring_modulator", StudioRingModulatorSettings),
    STUDIO_EFFECT_BITCRUSHER: ("bitcrusher", StudioBitcrusherSettings),
    STUDIO_EFFECT_DISTORTION: ("distortion", StudioDistortionSettings),
    STUDIO_EFFECT_LEVEL_MATCH: ("level_match", StudioLevelMatchSettings),
}


def character_effect_name(effect_kind: str) -> str:
    return studio_effect_name(effect_kind)


class StudioCharacterEffectEditor(QWidget):
    effect_changed = Signal(object)
    remove_requested = Signal(str)

    def __init__(self, effect_kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if effect_kind not in _FIELD_SPECS:
            raise ValueError(f"Unsupported character effect: {effect_kind}")
        self.setObjectName("StudioCharacterEffectEditor")
        self.effect_kind = effect_kind
        self._effect: StudioEffect | None = None
        self._loading = False
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(24)
        self._change_timer.timeout.connect(self._emit_changed)
        self.controls: dict[str, ScrollSafeSpinBox] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.info_buttons: dict[str, InfoPopoverButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_preset_section())
        self.reference_status = QLabel()
        self.reference_status.setObjectName("StudioEffectReferenceStatus")
        self.reference_status.setWordWrap(True)
        self.reference_status.setVisible(effect_kind == STUDIO_EFFECT_LEVEL_MATCH)
        layout.addWidget(self.reference_status)
        layout.addWidget(self._build_controls_section())
        self.remove_button = FeedbackButton()
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.clicked.connect(self._request_remove)
        layout.addWidget(self.remove_button)
        layout.addStretch(1)
        self.apply_language()

    def _build_preset_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioCharacterFxPresetSection")
        self.preset_label = QLabel()
        self.preset_label.setObjectName("StudioInspectorSectionTitle")
        self.preset_combo = ScrollSafeComboBox()
        self.preset_combo.setObjectName("StudioCharacterFxPresetCombo")
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.preset_combo.currentIndexChanged.connect(self._apply_selected_preset)
        self.enabled_button = FeedbackButton()
        self.enabled_button.setObjectName("StudioEffectToggle")
        self.enabled_button.setCheckable(True)
        self.enabled_button.setChecked(True)
        self.enabled_button.setFixedSize(54, 32)
        self.enabled_button.toggled.connect(self._set_enabled)
        layout = QHBoxLayout(section)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(self.preset_label)
        layout.addWidget(self.preset_combo, 1)
        layout.addWidget(self.enabled_button)
        return section

    def _build_controls_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("StudioCharacterFxSection")
        grid = QGridLayout(section)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, (name, label_key, minimum, maximum, step, suffix) in enumerate(
            _FIELD_SPECS[self.effect_kind]
        ):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            label = QLabel()
            label.setObjectName("MutedText")
            info = InfoPopoverButton()
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(5)
            label_row.addWidget(label)
            label_row.addWidget(info)
            label_row.addStretch(1)
            control = ScrollSafeSpinBox()
            control.setObjectName("StudioCharacterFxControl")
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setSuffix(suffix)
            control.valueChanged.connect(self._queue_changed)
            control.editingFinished.connect(self._flush_changed)
            self.controls[name] = control
            self.field_labels[name] = label
            self.info_buttons[name] = info
            field_layout.addLayout(label_row)
            field_layout.addWidget(control)
            grid.addWidget(field, index // 2, index % 2)
        return section

    def apply_language(self) -> None:
        selected = self.preset_combo.currentData()
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_label.setText(tr("Preset"))
        self.preset_combo.clear()
        for preset_id in EFFECT_PRESETS[self.effect_kind]:
            self.preset_combo.addItem(tr(_PRESET_NAMES[preset_id]), preset_id)
        self.preset_combo.addItem(tr("Custom"), "custom")
        self._select_preset(str(selected or "custom"))
        del blocker
        for name, label_key, *_rest in _FIELD_SPECS[self.effect_kind]:
            title = tr(label_key)
            detail = tr(_FIELD_HELP[name])
            self.field_labels[name].setText(title)
            self.info_buttons[name].set_content(title, detail)
            self.controls[name].setToolTip(detail)
        self.remove_button.setText(tr("Remove Effect"))
        self._sync_enabled_button(self.enabled_button.isChecked())
        self._sync_reference_status()

    def set_effect(self, effect: StudioEffect) -> None:
        if effect.kind != self.effect_kind:
            raise ValueError("Effect kind does not match this editor.")
        self._change_timer.stop()
        self._loading = True
        self._effect = effect
        settings_name, _settings_type = _SETTINGS_TYPES[self.effect_kind]
        settings = getattr(effect, settings_name)
        for name, control in self.controls.items():
            control.setValue(getattr(settings, name))
        self._select_preset(matching_character_effect_preset(effect))
        blocker = QSignalBlocker(self.enabled_button)
        self.enabled_button.setChecked(effect.enabled)
        del blocker
        self._sync_enabled_button(effect.enabled)
        self._loading = False

    def set_reference_available(self, available: bool) -> None:
        self.reference_status.setProperty("available", bool(available))
        self._sync_reference_status()

    def _sync_reference_status(self) -> None:
        if self.effect_kind != STUDIO_EFFECT_LEVEL_MATCH:
            return
        available = bool(self.reference_status.property("available"))
        self.reference_status.setText(
            tr("Original vocal detected")
            if available
            else tr("No matching original vocal - effect is bypassed")
        )
        self.reference_status.style().unpolish(self.reference_status)
        self.reference_status.style().polish(self.reference_status)

    def _select_preset(self, preset_id: str) -> None:
        index = self.preset_combo.findData(preset_id)
        if index < 0:
            index = self.preset_combo.findData("custom")
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.setCurrentIndex(index)
        del blocker

    def _apply_selected_preset(self, _index: int) -> None:
        if self._loading:
            return
        preset = EFFECT_PRESETS[self.effect_kind].get(str(self.preset_combo.currentData()))
        if preset is None:
            return
        self._loading = True
        for name, control in self.controls.items():
            control.setValue(getattr(preset, name))
        self._loading = False
        self._emit_changed()

    def _current_effect(self) -> StudioEffect | None:
        if self._effect is None:
            return None
        settings_name, settings_type = _SETTINGS_TYPES[self.effect_kind]
        settings = settings_type(**{name: control.value() for name, control in self.controls.items()})
        return replace(self._effect, **{settings_name: settings})

    def _queue_changed(self, _value: int) -> None:
        if self._loading:
            return
        self._select_preset("custom")
        self._change_timer.start()

    def _flush_changed(self) -> None:
        if self._change_timer.isActive():
            self._change_timer.stop()
            self._emit_changed()

    def _emit_changed(self) -> None:
        effect = self._current_effect()
        if self._loading or effect is None:
            return
        self._effect = effect
        self.effect_changed.emit(effect)

    def _set_enabled(self, enabled: bool) -> None:
        self._sync_enabled_button(enabled)
        if self._loading or self._effect is None:
            return
        self._effect = replace(self._current_effect(), enabled=enabled)
        self.effect_changed.emit(self._effect)

    def _sync_enabled_button(self, enabled: bool) -> None:
        self.enabled_button.setText(tr("On") if enabled else tr("Off"))
        self.enabled_button.setToolTip(tr("Enable or bypass this effect"))

    def _request_remove(self) -> None:
        if self._effect is not None:
            self.remove_requested.emit(self._effect.effect_id)
