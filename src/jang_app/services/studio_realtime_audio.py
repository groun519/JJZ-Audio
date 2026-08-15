from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from jang_app.services.audio_delay import delay_tail_ms
from jang_app.services.audio_doubler import doubler_tail_ms
from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.audio_player import PreparedPlaybackAudio, read_playback_audio
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.studio_pitch import prepare_pitch_shifted_audio
from jang_app.services.studio_session import (
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_DOUBLER,
    STUDIO_EFFECT_REVERB,
    StudioEffect,
)


STUDIO_PREVIEW_SAMPLE_RATE = 44_100


def prepare_studio_playback_audio(
    sources: Sequence[AudioMixSource],
) -> PreparedPlaybackAudio:
    tracks: list[np.ndarray] = []
    effect_chains = []
    duration_frames = 0
    for source in sources:
        pitched_path = prepare_pitch_shifted_audio(source.path, source.pitch_semitones)
        audio = read_playback_audio(prepare_preview_audio(pitched_path))
        source_start = max(0, round(source.source_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        source_end = (
            audio.shape[0]
            if source.source_end_ms is None
            else max(0, round(source.source_end_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        )
        trimmed = audio[source_start : min(source_end, audio.shape[0])]
        reference = None
        if source.reference_path is not None and source.reference_path.expanduser().is_file():
            reference_audio = read_playback_audio(
                prepare_preview_audio(source.reference_path)
            )
            reference = reference_audio[
                source_start : min(source_end, reference_audio.shape[0])
            ]
        level_effects = tuple(
            effect
            for effect in source.effects
            if effect.kind == STUDIO_EFFECT_LEVEL_MATCH
        )
        processed = process_mix_source(
            trimmed,
            STUDIO_PREVIEW_SAMPLE_RATE,
            fade_in_ms=source.fade_in_ms,
            fade_out_ms=source.fade_out_ms,
            pan_percent=source.pan_percent,
            effects=level_effects,
            reference_audio=reference,
        )
        timeline_start = max(
            0,
            round(source.timeline_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000),
        )
        aligned = np.zeros((timeline_start + processed.shape[0], 2), dtype=np.float32)
        aligned[timeline_start:] = processed[:, :2]
        tracks.append(aligned)
        effect_chains.append(_realtime_effects(source.effects))
        duration_frames = max(
            duration_frames,
            aligned.shape[0] + _effect_tail_frames(source),
        )
    return PreparedPlaybackAudio(
        tracks=tuple(tracks),
        duration_frames=duration_frames,
        effect_chains=tuple(effect_chains),
    )


def studio_effect_chains(
    sources: Sequence[AudioMixSource],
) -> tuple[tuple[StudioEffect, ...], ...]:
    return tuple(_realtime_effects(source.effects) for source in sources)


def studio_source_layout_signature(sources: Sequence[AudioMixSource]) -> tuple[object, ...]:
    return tuple(
        (
            source.path.expanduser().resolve(),
            source.timeline_start_ms,
            source.source_start_ms,
            source.source_end_ms,
            source.fade_in_ms,
            source.fade_out_ms,
            source.pan_percent,
            source.pitch_semitones,
            source.reference_path.expanduser().resolve()
            if source.reference_path is not None
            else None,
            tuple(
                effect
                for effect in source.effects
                if effect.kind == STUDIO_EFFECT_LEVEL_MATCH
            ),
        )
        for source in sources
    )


def studio_playback_duration_ms(
    sources: Sequence[AudioMixSource],
    *,
    minimum_ms: int = 0,
) -> int:
    duration_ms = max(0, int(minimum_ms))
    for source in sources:
        source_duration = max(
            0,
            (source.source_end_ms or source.source_start_ms) - source.source_start_ms,
        )
        duration_ms = max(
            duration_ms,
            source.timeline_start_ms + source_duration + _effect_tail_ms(source),
        )
    return duration_ms


def _effect_tail_frames(source: AudioMixSource) -> int:
    return round(_effect_tail_ms(source) * STUDIO_PREVIEW_SAMPLE_RATE / 1_000)


def _realtime_effects(effects: tuple[StudioEffect, ...]) -> tuple[StudioEffect, ...]:
    return tuple(effect for effect in effects if effect.kind != STUDIO_EFFECT_LEVEL_MATCH)


def _effect_tail_ms(source: AudioMixSource) -> int:
    total = 0
    for effect in source.effects:
        if not effect.enabled:
            continue
        if effect.kind == STUDIO_EFFECT_REVERB:
            total += max(0, effect.reverb.pre_delay_ms) + effect.reverb.decay_ms + 250
        elif effect.kind == STUDIO_EFFECT_DELAY:
            total += delay_tail_ms(effect.delay)
        elif effect.kind == STUDIO_EFFECT_DOUBLER:
            total += doubler_tail_ms(effect.doubler)
    return total
