from __future__ import annotations

import math


STUDIO_CLIP_GAIN_MIN_DB = -100.0
STUDIO_CLIP_GAIN_MAX_DB = 30.0
STUDIO_TRACK_VOLUME_MAX_PERCENT = 200
STUDIO_SOURCE_VOLUME_MAX = (
    STUDIO_TRACK_VOLUME_MAX_PERCENT
    / 100.0
    * math.pow(10.0, STUDIO_CLIP_GAIN_MAX_DB / 20.0)
)


def clamp_studio_clip_gain_db(value: float) -> float:
    return max(STUDIO_CLIP_GAIN_MIN_DB, min(STUDIO_CLIP_GAIN_MAX_DB, float(value)))


def clamp_studio_source_volume(value: float) -> float:
    return max(0.0, min(STUDIO_SOURCE_VOLUME_MAX, float(value)))


def studio_source_gain(volume_percent: int | float, clip_gain_db: float = 0.0) -> float:
    """Return the effective linear gain shared by waveform and export paths."""
    track_gain = max(0.0, min(STUDIO_TRACK_VOLUME_MAX_PERCENT, float(volume_percent))) / 100.0
    clip_gain = math.pow(10.0, clamp_studio_clip_gain_db(clip_gain_db) / 20.0)
    return clamp_studio_source_volume(track_gain * clip_gain)
