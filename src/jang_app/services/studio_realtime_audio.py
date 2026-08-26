from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from jang_app.services.audio_delay import delay_tail_ms
from jang_app.services.audio_doubler import doubler_tail_ms
from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.audio_player import PreparedPlaybackAudio, read_playback_audio
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.studio_pitch import prepare_pitch_shifted_audio
from jang_app.services.studio_session import (
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
    track_start_frames: list[int] = []
    track_effect_end_frames: list[int] = []
    duration_frames = 0
    pitched_paths: dict[tuple[Path, int], Path] = {}
    decoded_audio: dict[Path, np.ndarray] = {}
    for source in sources:
        source_key = (source.path.expanduser().resolve(), int(source.pitch_semitones))
        pitched_path = pitched_paths.get(source_key)
        if pitched_path is None:
            pitched_path = prepare_pitch_shifted_audio(source.path, source.pitch_semitones)
            pitched_paths[source_key] = pitched_path
        preview_path = prepare_preview_audio(pitched_path).expanduser().resolve()
        audio = decoded_audio.get(preview_path)
        if audio is None:
            audio = read_playback_audio(preview_path)
            decoded_audio[preview_path] = audio
        source_start = max(0, round(source.source_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        source_end = (
            audio.shape[0]
            if source.source_end_ms is None
            else max(0, round(source.source_end_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        )
        trimmed = audio[source_start : min(source_end, audio.shape[0])]
        reference = None
        if source.reference_path is not None and source.reference_path.expanduser().is_file():
            reference_path = prepare_preview_audio(source.reference_path).expanduser().resolve()
            reference_audio = decoded_audio.get(reference_path)
            if reference_audio is None:
                reference_audio = read_playback_audio(reference_path)
                decoded_audio[reference_path] = reference_audio
            reference = reference_audio[
                source_start : min(source_end, reference_audio.shape[0])
            ]
        processed = process_mix_source(
            trimmed,
            STUDIO_PREVIEW_SAMPLE_RATE,
            volume=source.volume,
            fade_in_ms=source.fade_in_ms,
            fade_out_ms=source.fade_out_ms,
            pan_percent=source.pan_percent,
            effects=source.effects,
            reference_audio=reference,
        )
        timeline_start = max(
            0,
            round(source.timeline_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000),
        )
        tracks.append(processed[:, :2])
        track_start_frames.append(timeline_start)
        effect_chains.append(())
        effect_end_frame = timeline_start + processed.shape[0]
        track_effect_end_frames.append(effect_end_frame)
        duration_frames = max(
            duration_frames,
            effect_end_frame,
        )
    return PreparedPlaybackAudio(
        tracks=tuple(tracks),
        duration_frames=duration_frames,
        effect_chains=tuple(effect_chains),
        track_start_frames=tuple(track_start_frames),
        track_effect_end_frames=tuple(track_effect_end_frames),
    )


def studio_effect_chains(
    sources: Sequence[AudioMixSource],
) -> tuple[tuple[StudioEffect, ...], ...]:
    return tuple(() for _source in sources)


def studio_source_layout_signature(sources: Sequence[AudioMixSource]) -> tuple[object, ...]:
    return tuple(
        (
            source.path.expanduser().resolve(),
            source.timeline_start_ms,
            source.source_start_ms,
            source.source_end_ms,
            source.fade_in_ms,
            source.fade_out_ms,
            source.volume,
            source.pan_percent,
            source.pitch_semitones,
            source.reference_path.expanduser().resolve()
            if source.reference_path is not None
            else None,
            source.effects,
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
