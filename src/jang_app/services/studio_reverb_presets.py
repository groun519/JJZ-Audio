from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.studio_session import StudioReverbSettings


CUSTOM_REVERB_PRESET = "custom"


@dataclass(frozen=True)
class StudioReverbPreset:
    key: str
    name: str
    settings: StudioReverbSettings


STUDIO_REVERB_PRESETS = (
    StudioReverbPreset(
        "natural_vocal",
        "Natural",
        StudioReverbSettings(),
    ),
    StudioReverbPreset(
        "warm_room",
        "Warm",
        StudioReverbSettings(
            room_height_m=2.8,
            room_length_m=5.0,
            room_width_m=4.0,
            pre_delay_ms=12,
            decay_ms=1_200,
            distance_m=1.5,
            brightness_percent=38,
            modulation_percent=3,
            early_high_hz=7_500,
            early_low_gain_db=1.0,
            early_high_gain_db=-2.0,
            reverb_high_hz=6_500,
            reverb_low_gain_db=1.5,
            reverb_high_gain_db=-3.0,
            dry_wet_percent=24,
            early_gain_db=-2.0,
            reverb_gain_db=-1.0,
        ),
    ),
    StudioReverbPreset(
        "vocal_plate",
        "Plate",
        StudioReverbSettings(
            room_height_m=3.0,
            room_length_m=8.0,
            room_width_m=7.0,
            pre_delay_ms=28,
            decay_ms=1_800,
            distance_m=2.0,
            brightness_percent=68,
            modulation_percent=10,
            early_low_gain_db=-2.0,
            early_high_gain_db=1.0,
            reverb_low_gain_db=-2.0,
            reverb_high_gain_db=1.0,
            dry_wet_percent=25,
            early_gain_db=-5.0,
        ),
    ),
    StudioReverbPreset(
        "wide_hall",
        "Hall",
        StudioReverbSettings(
            room_height_m=8.0,
            room_length_m=18.0,
            room_width_m=24.0,
            pre_delay_ms=45,
            decay_ms=2_800,
            distance_m=5.0,
            brightness_percent=52,
            modulation_percent=12,
            early_low_hz=250,
            early_high_hz=8_000,
            early_high_gain_db=-1.5,
            reverb_low_hz=220,
            reverb_high_hz=8_000,
            reverb_low_gain_db=1.0,
            reverb_high_gain_db=-1.0,
            dry_wet_percent=30,
            early_gain_db=-3.0,
        ),
    ),
    StudioReverbPreset(
        "dreamy",
        "Dream",
        StudioReverbSettings(
            room_height_m=10.0,
            room_length_m=24.0,
            room_width_m=28.0,
            pre_delay_ms=70,
            decay_ms=4_000,
            distance_m=7.0,
            brightness_percent=72,
            modulation_percent=35,
            early_low_hz=220,
            early_high_hz=12_000,
            early_low_gain_db=-3.0,
            early_high_gain_db=1.5,
            reverb_low_hz=180,
            reverb_high_hz=12_000,
            reverb_low_gain_db=-3.0,
            reverb_high_gain_db=2.0,
            dry_wet_percent=42,
            early_gain_db=-6.0,
            reverb_gain_db=1.0,
        ),
    ),
    StudioReverbPreset(
        "bloom",
        "Bloom",
        StudioReverbSettings(
            room_height_m=10.0,
            room_length_m=16.0,
            room_width_m=20.0,
            pre_delay_ms=50,
            decay_ms=950,
            distance_m=10.0,
            brightness_percent=50,
            modulation_percent=2,
            dry_wet_percent=30,
        ),
    ),
)


def reverb_preset_settings(key: str) -> StudioReverbSettings | None:
    return next(
        (preset.settings for preset in STUDIO_REVERB_PRESETS if preset.key == key),
        None,
    )


def matching_reverb_preset(settings: StudioReverbSettings) -> str:
    return next(
        (
            preset.key
            for preset in STUDIO_REVERB_PRESETS
            if preset.settings == settings
        ),
        CUSTOM_REVERB_PRESET,
    )
