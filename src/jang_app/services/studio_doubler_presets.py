from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.studio_session import StudioDoublerSettings


CUSTOM_DOUBLER_PRESET = "custom"


@dataclass(frozen=True)
class StudioDoublerPreset:
    key: str
    name: str
    settings: StudioDoublerSettings


STUDIO_DOUBLER_PRESETS = (
    StudioDoublerPreset(
        "natural",
        "Natural",
        StudioDoublerSettings(),
    ),
    StudioDoublerPreset(
        "wide",
        "Wide",
        StudioDoublerSettings(24, 9, 90, 28),
    ),
    StudioDoublerPreset(
        "chorus",
        "Chorus",
        StudioDoublerSettings(28, 14, 100, 38),
    ),
)


def doubler_preset_settings(key: str) -> StudioDoublerSettings | None:
    return next(
        (preset.settings for preset in STUDIO_DOUBLER_PRESETS if preset.key == key),
        None,
    )


def matching_doubler_preset(settings: StudioDoublerSettings) -> str:
    return next(
        (
            preset.key
            for preset in STUDIO_DOUBLER_PRESETS
            if preset.settings == settings
        ),
        CUSTOM_DOUBLER_PRESET,
    )
