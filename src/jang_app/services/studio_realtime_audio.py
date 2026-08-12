from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.audio_player import PreparedPlaybackAudio, read_playback_audio
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.studio_session import STUDIO_EFFECT_REVERB, StudioEffect


STUDIO_PREVIEW_SAMPLE_RATE = 44_100


def prepare_studio_playback_audio(
    sources: Sequence[AudioMixSource],
) -> PreparedPlaybackAudio:
    tracks: list[np.ndarray] = []
    effect_chains = []
    duration_frames = 0
    for source in sources:
        audio = read_playback_audio(prepare_preview_audio(source.path))
        source_start = max(0, round(source.source_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        source_end = (
            audio.shape[0]
            if source.source_end_ms is None
            else max(0, round(source.source_end_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000))
        )
        trimmed = audio[source_start : min(source_end, audio.shape[0])]
        processed = process_mix_source(
            trimmed,
            STUDIO_PREVIEW_SAMPLE_RATE,
            fade_in_ms=source.fade_in_ms,
            fade_out_ms=source.fade_out_ms,
            pan_percent=source.pan_percent,
        )
        timeline_start = max(
            0,
            round(source.timeline_start_ms * STUDIO_PREVIEW_SAMPLE_RATE / 1_000),
        )
        aligned = np.zeros((timeline_start + processed.shape[0], 2), dtype=np.float32)
        aligned[timeline_start:] = processed[:, :2]
        tracks.append(aligned)
        effect_chains.append(source.effects)
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
    return tuple(source.effects for source in sources)


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


def _effect_tail_ms(source: AudioMixSource) -> int:
    return max(
        (
            effect.reverb.pre_delay_ms + effect.reverb.decay_ms + 250
            for effect in source.effects
            if effect.enabled and effect.kind == STUDIO_EFFECT_REVERB
        ),
        default=0,
    )
