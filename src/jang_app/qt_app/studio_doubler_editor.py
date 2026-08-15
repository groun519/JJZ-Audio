from __future__ import annotations

from PySide6.QtWidgets import QWidget

from jang_app.qt_app.studio_simple_effect_editor import (
    SimpleEffectEditorSpec,
    SimpleEffectField,
    SimpleEffectPreset,
    StudioSimpleEffectEditor,
)
from jang_app.services.studio_doubler_presets import (
    CUSTOM_DOUBLER_PRESET,
    STUDIO_DOUBLER_PRESETS,
)
from jang_app.services.studio_session import STUDIO_EFFECT_DOUBLER, StudioDoublerSettings


_SPEC = SimpleEffectEditorSpec(
    effect_kind=STUDIO_EFFECT_DOUBLER,
    settings_field="doubler",
    settings_factory=StudioDoublerSettings,
    custom_preset=CUSTOM_DOUBLER_PRESET,
    presets=tuple(
        SimpleEffectPreset(preset.key, preset.name, preset.settings)
        for preset in STUDIO_DOUBLER_PRESETS
    ),
    groups=(
        ("Voices", ("voice_spacing_ms", "pitch_spread_cents")),
        ("Output", ("stereo_width_percent", "dry_wet_percent")),
    ),
    fields=(
        SimpleEffectField(
            "voice_spacing_ms",
            "Spacing",
            6,
            40,
            1,
            " ms",
            "Sets how far the doubled voices sit behind the original vocal.",
            "Use 12-22 ms for a natural double and longer values for a chorus-like sound.",
        ),
        SimpleEffectField(
            "pitch_spread_cents",
            "Detune",
            0,
            20,
            1,
            " cent",
            "Adds tiny independent pitch movement so the copies do not sound identical.",
            "Start around 5-9 cents. Higher values sound wider but less natural.",
        ),
        SimpleEffectField(
            "stereo_width_percent",
            "Width",
            0,
            100,
            1,
            "%",
            "Moves the doubled voices toward opposite sides of the stereo image.",
            "Use 40-65% for a centered lead vocal and 80% or more for a wide chorus.",
        ),
        SimpleEffectField(
            "dry_wet_percent",
            "Dry / Wet",
            0,
            100,
            1,
            "%",
            "Balances the original vocal and the doubled voices.",
            "Start around 18-30% to add thickness without blurring the words.",
        ),
    ),
    preset_detail="Choose how thick and wide the doubled vocal should sound.",
    preset_recommendation="Natural keeps the lead centered; Wide and Chorus are more obvious.",
)


class StudioDoublerEditor(StudioSimpleEffectEditor):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_SPEC, parent)
        self.setObjectName("StudioDoublerEditor")
