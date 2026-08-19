from __future__ import annotations

from uuid import uuid4

from jang_app.services.studio_character_fx_presets import (
    character_effect,
    character_effect_chain,
)
from jang_app.services.studio_delay_presets import delay_preset_settings
from jang_app.services.studio_reverb_presets import reverb_preset_settings
from jang_app.services.studio_session import (
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_REVERB,
    StudioEffect,
)


KARAOKE_PRESET = "karaoke"
LUSH_PRESET = "lush"


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
    return character_effect_chain(preset_id)
