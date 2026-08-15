from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from jang_app.services.studio_session import (
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_DOUBLER,
    STUDIO_EFFECT_DISTORTION,
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_RADIO_FILTER,
    STUDIO_EFFECT_REVERB,
    STUDIO_EFFECT_RING_MODULATOR,
    StudioBitcrusherSettings,
    StudioDistortionSettings,
    StudioEffect,
    StudioLevelMatchSettings,
    StudioRadioFilterSettings,
    StudioRingModulatorSettings,
)


CHARACTER_EFFECT_KINDS = (
    STUDIO_EFFECT_RADIO_FILTER,
    STUDIO_EFFECT_RING_MODULATOR,
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DISTORTION,
)
SOURCE_AWARE_EFFECT_KINDS = (STUDIO_EFFECT_LEVEL_MATCH,)
EDITABLE_EFFECT_KINDS = (*CHARACTER_EFFECT_KINDS, *SOURCE_AWARE_EFFECT_KINDS)

STUDIO_EFFECT_NAMES = {
    STUDIO_EFFECT_REVERB: "Reverb",
    STUDIO_EFFECT_DELAY: "Delay",
    STUDIO_EFFECT_DOUBLER: "Doubler",
    STUDIO_EFFECT_RADIO_FILTER: "Radio Filter",
    STUDIO_EFFECT_RING_MODULATOR: "Ring Modulator",
    STUDIO_EFFECT_BITCRUSHER: "Bitcrusher",
    STUDIO_EFFECT_DISTORTION: "Distortion",
    STUDIO_EFFECT_LEVEL_MATCH: "Level Match",
}

EFFECT_PRESETS = {
    STUDIO_EFFECT_RADIO_FILTER: {
        "telephone": StudioRadioFilterSettings(300, 3_400, 100),
        "walkie_talkie": StudioRadioFilterSettings(420, 2_900, 100),
        "old_speaker": StudioRadioFilterSettings(180, 5_200, 85),
    },
    STUDIO_EFFECT_RING_MODULATOR: {
        "subtle_metal": StudioRingModulatorSettings(38, 16),
        "robot": StudioRingModulatorSettings(72, 30),
        "alarm": StudioRingModulatorSettings(145, 45),
    },
    STUDIO_EFFECT_BITCRUSHER: {
        "light_digital": StudioBitcrusherSettings(12, 22_050, 25),
        "retro_10bit": StudioBitcrusherSettings(10, 16_000, 42),
        "broken_8bit": StudioBitcrusherSettings(8, 8_000, 62),
    },
    STUDIO_EFFECT_DISTORTION: {
        "warm": StudioDistortionSettings(22, 18),
        "grit": StudioDistortionSettings(48, 32),
        "overdrive": StudioDistortionSettings(76, 48),
    },
    STUDIO_EFFECT_LEVEL_MATCH: {
        "natural": StudioLevelMatchSettings(55, 260, 4, -48),
        "balanced": StudioLevelMatchSettings(75, 180, 6, -50),
        "strong": StudioLevelMatchSettings(90, 100, 9, -55),
    },
}

CHAIN_PRESETS = {
    "animatronic": (
        (STUDIO_EFFECT_RADIO_FILTER, "old_speaker"),
        (STUDIO_EFFECT_RING_MODULATOR, "robot"),
        (STUDIO_EFFECT_BITCRUSHER, "light_digital"),
        (STUDIO_EFFECT_DISTORTION, "grit"),
    ),
    "walkie_talkie": (
        (STUDIO_EFFECT_RADIO_FILTER, "walkie_talkie"),
        (STUDIO_EFFECT_BITCRUSHER, "light_digital"),
        (STUDIO_EFFECT_DISTORTION, "warm"),
    ),
    "broken_robot": (
        (STUDIO_EFFECT_RADIO_FILTER, "telephone"),
        (STUDIO_EFFECT_RING_MODULATOR, "alarm"),
        (STUDIO_EFFECT_BITCRUSHER, "broken_8bit"),
        (STUDIO_EFFECT_DISTORTION, "overdrive"),
    ),
}


def character_effect(effect_kind: str, preset_id: str | None = None) -> StudioEffect:
    effect = StudioEffect(f"fx-{uuid4().hex}", effect_kind)
    presets = EFFECT_PRESETS.get(effect_kind, {})
    selected = presets.get(preset_id or "")
    if selected is None:
        return effect
    field = _settings_field(effect_kind)
    return replace(effect, **{field: selected})


def character_effect_chain(preset_id: str) -> tuple[StudioEffect, ...]:
    return tuple(
        character_effect(effect_kind, effect_preset)
        for effect_kind, effect_preset in CHAIN_PRESETS.get(preset_id, ())
    )


def matching_character_effect_preset(effect: StudioEffect) -> str:
    settings = getattr(effect, _settings_field(effect.kind), None)
    for preset_id, preset in EFFECT_PRESETS.get(effect.kind, {}).items():
        if settings == preset:
            return preset_id
    return "custom"


def studio_effect_name(effect_kind: str) -> str:
    return STUDIO_EFFECT_NAMES.get(effect_kind, "Effect")


def _settings_field(effect_kind: str) -> str:
    return {
        STUDIO_EFFECT_RADIO_FILTER: "radio_filter",
        STUDIO_EFFECT_RING_MODULATOR: "ring_modulator",
        STUDIO_EFFECT_BITCRUSHER: "bitcrusher",
        STUDIO_EFFECT_DISTORTION: "distortion",
        STUDIO_EFFECT_LEVEL_MATCH: "level_match",
    }[effect_kind]
