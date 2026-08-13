from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


PRESET_BALANCED = "balanced"
PRESET_TIMBRE = "timbre"
PRESET_DETAIL = "detail"
PRESET_CUSTOM = "custom"
RVC_INFERENCE_PRESETS = (PRESET_BALANCED, PRESET_TIMBRE, PRESET_DETAIL)


@dataclass(frozen=True)
class RvcInferenceSettings:
    index_rate: float = 0.75
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect: float = 0.33


_PRESETS = {
    PRESET_BALANCED: RvcInferenceSettings(),
    PRESET_TIMBRE: RvcInferenceSettings(index_rate=0.90),
    PRESET_DETAIL: RvcInferenceSettings(index_rate=0.55, protect=0.20),
}


def rvc_inference_preset(preset_id: str) -> RvcInferenceSettings:
    try:
        return _PRESETS[preset_id]
    except KeyError as exc:
        raise ValueError(f"Unknown RVC inference preset: {preset_id}") from exc


def matching_rvc_inference_preset(settings: RvcInferenceSettings) -> str:
    normalized = normalize_rvc_inference_settings(settings)
    return next(
        (preset_id for preset_id, preset in _PRESETS.items() if preset == normalized),
        PRESET_CUSTOM,
    )


def rvc_inference_settings_from_data(value: object) -> RvcInferenceSettings:
    if not isinstance(value, Mapping):
        return RvcInferenceSettings()
    defaults = RvcInferenceSettings()
    return normalize_rvc_inference_settings(
        RvcInferenceSettings(
            index_rate=_float_value(value.get("index_rate"), defaults.index_rate),
            filter_radius=_int_value(value.get("filter_radius"), defaults.filter_radius),
            rms_mix_rate=_float_value(value.get("rms_mix_rate"), defaults.rms_mix_rate),
            protect=_float_value(value.get("protect"), defaults.protect),
        )
    )


def normalize_rvc_inference_settings(settings: RvcInferenceSettings) -> RvcInferenceSettings:
    return RvcInferenceSettings(
        index_rate=_clamp_float(settings.index_rate, 0.0, 1.0),
        filter_radius=max(0, min(7, int(settings.filter_radius))),
        rms_mix_rate=_clamp_float(settings.rms_mix_rate, 0.0, 1.0),
        protect=_clamp_float(settings.protect, 0.0, 0.5),
    )


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, float(value))), 2)


def _float_value(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
