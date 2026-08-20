from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.studio_session import StudioHardTuneSettings


CUSTOM_HARD_TUNE_PRESET = "custom"


@dataclass(frozen=True)
class StudioHardTunePreset:
    key: str
    name: str
    settings: StudioHardTuneSettings


STUDIO_HARD_TUNE_PRESETS = (
    StudioHardTunePreset(
        "soft",
        "Soft",
        StudioHardTuneSettings(
            strength_percent=70,
            response_ms=110,
            vibrato_preserve_percent=50,
        ),
    ),
    StudioHardTunePreset(
        "synth",
        "Synth",
        StudioHardTuneSettings(
            strength_percent=95,
            response_ms=30,
            vibrato_preserve_percent=10,
        ),
    ),
    StudioHardTunePreset(
        "hard",
        "Hard",
        StudioHardTuneSettings(
            strength_percent=100,
            response_ms=10,
            vibrato_preserve_percent=0,
        ),
    ),
)


def hard_tune_preset_settings(key: str) -> StudioHardTuneSettings | None:
    return next(
        (preset.settings for preset in STUDIO_HARD_TUNE_PRESETS if preset.key == key),
        None,
    )


def matching_hard_tune_preset(settings: StudioHardTuneSettings) -> str:
    return next(
        (
            preset.key
            for preset in STUDIO_HARD_TUNE_PRESETS
            if preset.settings == settings
        ),
        CUSTOM_HARD_TUNE_PRESET,
    )
