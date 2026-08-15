from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.studio_session import StudioDelaySettings


CUSTOM_DELAY_PRESET = "custom"


@dataclass(frozen=True)
class StudioDelayPreset:
    key: str
    name: str
    settings: StudioDelaySettings


STUDIO_DELAY_PRESETS = (
    StudioDelayPreset(
        "karaoke",
        "Karaoke",
        StudioDelaySettings(190, 24, 20, 55),
    ),
    StudioDelayPreset(
        "slap",
        "Slap",
        StudioDelaySettings(110, 10, 18, 15),
    ),
    StudioDelayPreset(
        "vocal",
        "Vocal",
        StudioDelaySettings(),
    ),
    StudioDelayPreset(
        "wide",
        "Wide",
        StudioDelaySettings(440, 36, 28, 85),
    ),
    StudioDelayPreset(
        "dream",
        "Dream",
        StudioDelaySettings(680, 52, 35, 70),
    ),
)


def delay_preset_settings(key: str) -> StudioDelaySettings | None:
    return next(
        (preset.settings for preset in STUDIO_DELAY_PRESETS if preset.key == key),
        None,
    )


def matching_delay_preset(settings: StudioDelaySettings) -> str:
    return next(
        (
            preset.key
            for preset in STUDIO_DELAY_PRESETS
            if preset.settings == settings
        ),
        CUSTOM_DELAY_PRESET,
    )
