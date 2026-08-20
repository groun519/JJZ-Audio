from __future__ import annotations

from uuid import uuid4

from jang_app.services.studio_character_fx_presets import (
    character_effect,
    character_effect_chain,
)
from jang_app.services.studio_delay_presets import delay_preset_settings
from jang_app.services.studio_hard_tune_presets import hard_tune_preset_settings
from jang_app.services.studio_reverb_presets import reverb_preset_settings
from jang_app.services.studio_session import (
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DOUBLER,
    STUDIO_EFFECT_HARD_TUNE,
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_REVERB,
    StudioEffect,
    StudioBitcrusherSettings,
    StudioDoublerSettings,
    StudioReverbSettings,
)


KARAOKE_PRESET = "karaoke"
LUSH_PRESET = "lush"
SYNTH_PRESET = "synth"


def studio_effect_chain(preset_id: str) -> tuple[StudioEffect, ...]:
    if preset_id == KARAOKE_PRESET:
        delay = delay_preset_settings(KARAOKE_PRESET)
        reverb = reverb_preset_settings(KARAOKE_PRESET)
        if delay is None or reverb is None:
            return ()
        return (
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_DELAY,
                delay=delay,
            ),
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_REVERB,
                reverb=reverb,
            ),
        )
    if preset_id == LUSH_PRESET:
        reverb = reverb_preset_settings("bloom")
        if reverb is None:
            return ()
        return (
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_REVERB,
                reverb=reverb,
            ),
            character_effect(STUDIO_EFFECT_LEVEL_MATCH, "balanced"),
        )
    if preset_id == SYNTH_PRESET:
        hard_tune = hard_tune_preset_settings(SYNTH_PRESET)
        if hard_tune is None:
            return ()
        return (
            character_effect(STUDIO_EFFECT_LEVEL_MATCH, "balanced"),
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_HARD_TUNE,
                hard_tune=hard_tune,
            ),
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_DOUBLER,
                doubler=StudioDoublerSettings(12, 4, 60, 16),
            ),
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_BITCRUSHER,
                bitcrusher=StudioBitcrusherSettings(14, 32_000, 8),
            ),
            StudioEffect(
                effect_id=f"fx-{uuid4().hex}",
                kind=STUDIO_EFFECT_REVERB,
                reverb=StudioReverbSettings(
                    room_height_m=3.0,
                    room_length_m=6.0,
                    room_width_m=7.0,
                    pre_delay_ms=18,
                    decay_ms=650,
                    distance_m=1.5,
                    brightness_percent=72,
                    modulation_percent=4,
                    early_high_gain_db=1.0,
                    reverb_high_gain_db=1.0,
                    dry_wet_percent=12,
                    early_gain_db=-5.0,
                    reverb_gain_db=-3.0,
                ),
            ),
        )
    return character_effect_chain(preset_id)
