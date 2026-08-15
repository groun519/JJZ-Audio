from __future__ import annotations

from PySide6.QtWidgets import QWidget

from jang_app.qt_app.studio_simple_effect_editor import (
    SimpleEffectEditorSpec,
    SimpleEffectField,
    SimpleEffectPreset,
    StudioSimpleEffectEditor,
)
from jang_app.services.studio_delay_presets import (
    CUSTOM_DELAY_PRESET,
    STUDIO_DELAY_PRESETS,
)
from jang_app.services.studio_session import STUDIO_EFFECT_DELAY, StudioDelaySettings


_SPEC = SimpleEffectEditorSpec(
    effect_kind=STUDIO_EFFECT_DELAY,
    settings_field="delay",
    settings_factory=StudioDelaySettings,
    custom_preset=CUSTOM_DELAY_PRESET,
    presets=tuple(
        SimpleEffectPreset(preset.key, preset.name, preset.settings)
        for preset in STUDIO_DELAY_PRESETS
    ),
    groups=(
        ("Repeats", ("delay_ms", "feedback_percent")),
        ("Output", ("dry_wet_percent", "stereo_width_percent")),
    ),
    fields=(
        SimpleEffectField(
            "delay_ms",
            "Repeat Interval",
            40,
            2_000,
            10,
            " ms",
            "Sets the time between the original voice and each repeat.",
            "Use 80-150 ms for a short slap and 250-500 ms for a clear vocal echo.",
        ),
        SimpleEffectField(
            "feedback_percent",
            "Feedback",
            0,
            85,
            1,
            "%",
            "Controls how long the repeats continue. Higher values create more echoes.",
            "Start around 20-35%. Values above 55% create a long repeating tail.",
        ),
        SimpleEffectField(
            "dry_wet_percent",
            "Dry / Wet",
            0,
            100,
            1,
            "%",
            "Balances the original voice and the repeated sound.",
            "Start around 15-30% so the words remain clear.",
        ),
        SimpleEffectField(
            "stereo_width_percent",
            "Stereo Width",
            0,
            100,
            1,
            "%",
            "Spreads the left and right repeats apart to make the echo feel wider.",
            "Use 20-50% for a natural vocal and higher values for an obvious stereo effect.",
        ),
    ),
    preset_detail="Choose a complete delay sound, then adjust the controls below.",
    preset_recommendation="Vocal is a balanced starting point for most lead vocals.",
)


class StudioDelayEditor(StudioSimpleEffectEditor):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_SPEC, parent)
        self.setObjectName("StudioDelayEditor")
