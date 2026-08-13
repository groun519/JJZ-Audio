from __future__ import annotations

import math

import numpy as np

from jang_app.services.audio_character_fx import apply_character_effect
from jang_app.services.audio_level_match import apply_vocal_level_match
from jang_app.services.audio_reverb import apply_reverb
from jang_app.services.studio_audio_levels import clamp_studio_source_volume
from jang_app.services.studio_character_fx_presets import CHARACTER_EFFECT_KINDS
from jang_app.services.studio_session import (
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_REVERB,
    StudioEffect,
)


def process_mix_source(
    audio: np.ndarray,
    sample_rate: int,
    *,
    volume: float = 1.0,
    fade_in_ms: int = 0,
    fade_out_ms: int = 0,
    pan_percent: int = 0,
    effects: tuple[StudioEffect, ...] = (),
    reference_audio: np.ndarray | None = None,
) -> np.ndarray:
    """Apply non-destructive clip and track processing before timeline mixing."""
    processed = np.asarray(audio, dtype=np.float32).copy()
    for effect in effects:
        if effect.enabled and effect.kind == STUDIO_EFFECT_LEVEL_MATCH:
            processed = apply_vocal_level_match(
                processed,
                reference_audio,
                sample_rate,
                effect.level_match,
            )
    processed *= clamp_studio_source_volume(volume)
    _apply_fades(processed, sample_rate, fade_in_ms, fade_out_ms)
    for effect in effects:
        if effect.enabled and effect.kind == STUDIO_EFFECT_REVERB:
            processed = apply_reverb(processed, sample_rate, effect.reverb)
        elif effect.enabled and effect.kind in CHARACTER_EFFECT_KINDS:
            processed = apply_character_effect(processed, sample_rate, effect)
    return _apply_pan(processed, pan_percent)


def _apply_fades(
    audio: np.ndarray,
    sample_rate: int,
    fade_in_ms: int,
    fade_out_ms: int,
) -> None:
    if audio.shape[0] == 0 or sample_rate <= 0:
        return
    fade_in_frames = min(audio.shape[0], max(0, round(fade_in_ms * sample_rate / 1_000)))
    fade_out_frames = min(
        max(0, audio.shape[0] - fade_in_frames),
        max(0, round(fade_out_ms * sample_rate / 1_000)),
    )
    if fade_in_frames:
        audio[:fade_in_frames] *= np.linspace(
            0.0,
            1.0,
            fade_in_frames,
            endpoint=True,
            dtype=np.float32,
        )[:, None]
    if fade_out_frames:
        audio[-fade_out_frames:] *= np.linspace(
            1.0,
            0.0,
            fade_out_frames,
            endpoint=True,
            dtype=np.float32,
        )[:, None]


def _apply_pan(audio: np.ndarray, pan_percent: int) -> np.ndarray:
    pan = max(-100, min(100, int(pan_percent))) / 100.0
    if pan == 0.0 or audio.shape[0] == 0:
        return audio
    stereo = audio if audio.shape[1] >= 2 else np.repeat(audio, 2, axis=1)
    angle = (pan + 1.0) * math.pi / 4.0
    left_gain = math.cos(angle) * math.sqrt(2.0)
    right_gain = math.sin(angle) * math.sqrt(2.0)
    panned = stereo.copy()
    panned[:, 0] *= left_gain
    panned[:, 1] *= right_gain
    return panned
