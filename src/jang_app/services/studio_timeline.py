from __future__ import annotations

import uuid
from dataclasses import replace

from jang_app.services.studio_audio_levels import clamp_studio_clip_gain_db
from jang_app.services.studio_pitch import clamp_studio_clip_pitch
from jang_app.services.studio_session import (
    TRACK_AUDIO,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioEffect,
    StudioMediaSettings,
    StudioSession,
    StudioTrack,
)


class StudioTimelineError(ValueError):
    """Raised when a non-destructive timeline edit is invalid."""


def session_duration_ms(session: StudioSession) -> int:
    return max(
        (clip.timeline_end_ms for track in session.tracks for clip in track.clips),
        default=0,
    )


def add_studio_clip(
    session: StudioSession,
    track_id: str,
    asset: StudioAssetRef,
    source_duration_ms: int,
    *,
    timeline_start_ms: int = 0,
) -> StudioSession:
    if source_duration_ms <= 0:
        raise StudioTimelineError("The source duration must be greater than zero.")
    target_track = _find_track(session, track_id)
    if not _track_accepts_asset(target_track, asset):
        raise StudioTimelineError("Media can only be placed on the media track.")
    clip = StudioClip(
        clip_id=f"clip-{uuid.uuid4().hex}",
        asset=asset,
        timeline_start_ms=max(0, int(timeline_start_ms)),
        source_start_ms=0,
        source_end_ms=int(source_duration_ms),
    )
    return _replace_track(
        session,
        track_id,
        lambda track: replace(track, clips=_sorted_clips((*track.clips, clip))),
    )


def add_studio_track(session: StudioSession, *, name: str = "") -> StudioSession:
    track_number = sum(track.role == TRACK_AUDIO for track in session.tracks) + 1
    track = StudioTrack(
        track_id=f"track-audio-{uuid.uuid4().hex}",
        name=name.strip() or f"Audio {track_number}",
        role=TRACK_AUDIO,
    )
    return replace(session, tracks=(*session.tracks, track))


def move_studio_clip(
    session: StudioSession,
    clip_id: str,
    *,
    track_id: str,
    timeline_start_ms: int,
) -> StudioSession:
    source_track, clip = _find_clip(session, clip_id)
    target_track = _find_track(session, track_id)
    if not _track_accepts_asset(target_track, clip.asset):
        raise StudioTimelineError("Media can only be placed on the media track.")
    updated_clip = replace(clip, timeline_start_ms=max(0, int(timeline_start_ms)))
    tracks: list[StudioTrack] = []
    for track in session.tracks:
        clips = tuple(candidate for candidate in track.clips if candidate.clip_id != clip_id)
        if track.track_id == target_track.track_id:
            clips = (*clips, updated_clip)
        tracks.append(replace(track, clips=_sorted_clips(clips)))
    if source_track.track_id == target_track.track_id:
        return replace(session, tracks=tuple(tracks))
    return replace(session, tracks=tuple(tracks))


def trim_studio_clip(
    session: StudioSession,
    clip_id: str,
    *,
    source_start_ms: int,
    source_end_ms: int,
    preserve_timeline_end: bool = False,
) -> StudioSession:
    track, clip = _find_clip(session, clip_id)
    start = max(0, int(source_start_ms))
    end = max(0, int(source_end_ms))
    if end <= start:
        raise StudioTimelineError("A clip must contain at least one millisecond of audio.")
    timeline_start = clip.timeline_start_ms
    if preserve_timeline_end:
        timeline_start += start - clip.source_start_ms
    updated = replace(
        clip,
        timeline_start_ms=max(0, timeline_start),
        source_start_ms=start,
        source_end_ms=end,
    )
    updated = _with_clamped_fades(updated)
    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(
            current,
            clips=_sorted_clips(
                tuple(updated if candidate.clip_id == clip_id else candidate for candidate in current.clips)
            ),
        ),
    )


def split_studio_clip(
    session: StudioSession,
    clip_id: str,
    *,
    timeline_position_ms: int,
) -> StudioSession:
    track, clip = _find_clip(session, clip_id)
    split_position = int(timeline_position_ms)
    if not clip.timeline_start_ms < split_position < clip.timeline_end_ms:
        raise StudioTimelineError("The playhead must be inside the selected clip.")

    source_split = clip.source_start_ms + split_position - clip.timeline_start_ms
    left = replace(clip, source_end_ms=source_split, fade_out_ms=0)
    right = replace(
        clip,
        clip_id=f"clip-{uuid.uuid4().hex}",
        timeline_start_ms=split_position,
        source_start_ms=source_split,
        fade_in_ms=0,
    )
    left = _with_clamped_fades(left)
    right = _with_clamped_fades(right)
    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(
            current,
            clips=_sorted_clips(
                tuple(
                    result
                    for candidate in current.clips
                    for result in (
                        (left, right) if candidate.clip_id == clip_id else (candidate,)
                    )
                )
            ),
        ),
    )


def remove_studio_clip(session: StudioSession, clip_id: str) -> StudioSession:
    track, _clip = _find_clip(session, clip_id)
    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(
            current,
            clips=tuple(candidate for candidate in current.clips if candidate.clip_id != clip_id),
        ),
    )


def add_studio_clip_effect(
    session: StudioSession,
    clip_id: str,
    effect: StudioEffect,
) -> StudioSession:
    track, clip = _find_clip(session, clip_id)
    if any(candidate.effect_id == effect.effect_id for candidate in clip.effects):
        raise StudioTimelineError(f"Studio effect already exists: {effect.effect_id}")
    return _replace_clip(
        session,
        track.track_id,
        clip_id,
        lambda candidate: replace(candidate, effects=(*candidate.effects, effect)),
    )


def update_studio_clip_effect(
    session: StudioSession,
    clip_id: str,
    effect: StudioEffect,
) -> StudioSession:
    track, clip = _find_clip(session, clip_id)
    if not any(candidate.effect_id == effect.effect_id for candidate in clip.effects):
        raise StudioTimelineError(f"Unknown Studio effect: {effect.effect_id}")
    return _replace_clip(
        session,
        track.track_id,
        clip_id,
        lambda candidate: replace(
            candidate,
            effects=tuple(
                effect if current.effect_id == effect.effect_id else current
                for current in candidate.effects
            ),
        ),
    )


def remove_studio_clip_effect(
    session: StudioSession,
    clip_id: str,
    effect_id: str,
) -> StudioSession:
    track, clip = _find_clip(session, clip_id)
    if not any(candidate.effect_id == effect_id for candidate in clip.effects):
        raise StudioTimelineError(f"Unknown Studio effect: {effect_id}")
    return _replace_clip(
        session,
        track.track_id,
        clip_id,
        lambda candidate: replace(
            candidate,
            effects=tuple(
                current for current in candidate.effects if current.effect_id != effect_id
            ),
        ),
    )


def remove_studio_track(session: StudioSession, track_id: str) -> StudioSession:
    _find_track(session, track_id)
    return replace(
        session,
        tracks=tuple(track for track in session.tracks if track.track_id != track_id),
    )


def set_studio_track_mix(
    session: StudioSession,
    track_id: str,
    *,
    muted: bool | None = None,
    solo: bool | None = None,
    volume_percent: int | None = None,
    pan_percent: int | None = None,
) -> StudioSession:
    def update(track: StudioTrack) -> StudioTrack:
        return replace(
            track,
            muted=track.muted if muted is None else bool(muted),
            solo=track.solo if solo is None else bool(solo),
            volume_percent=(
                track.volume_percent
                if volume_percent is None
                else max(0, min(200, int(volume_percent)))
            ),
            pan_percent=(
                track.pan_percent
                if pan_percent is None
                else max(-100, min(100, int(pan_percent)))
            ),
        )

    return _replace_track(session, track_id, update)


def set_studio_track_name(session: StudioSession, track_id: str, name: str) -> StudioSession:
    normalized = str(name).strip()
    if not normalized:
        raise StudioTimelineError("A track name cannot be empty.")
    return _replace_track(
        session,
        track_id,
        lambda track: replace(track, name=normalized) if track.role == TRACK_AUDIO else track,
    )


def set_studio_track_collapsed(
    session: StudioSession,
    track_id: str,
    collapsed: bool,
) -> StudioSession:
    return _replace_track(
        session,
        track_id,
        lambda track: replace(track, collapsed=bool(collapsed)),
    )


def set_studio_clip_gain(session: StudioSession, clip_id: str, gain_db: float) -> StudioSession:
    track, _clip = _find_clip(session, clip_id)
    clamped = clamp_studio_clip_gain_db(gain_db)
    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(
            current,
            clips=tuple(
                replace(candidate, gain_db=clamped)
                if candidate.clip_id == clip_id
                else candidate
                for candidate in current.clips
            ),
        ),
    )


def set_studio_clip_pitch(
    session: StudioSession,
    clip_id: str,
    pitch_semitones: int,
) -> StudioSession:
    track, _clip = _find_clip(session, clip_id)
    pitch = clamp_studio_clip_pitch(pitch_semitones)
    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(
            current,
            clips=tuple(
                replace(candidate, pitch_semitones=pitch)
                if candidate.clip_id == clip_id
                else candidate
                for candidate in current.clips
            ),
        ),
    )


def set_studio_clip_mix(
    session: StudioSession,
    clip_id: str,
    *,
    gain_db: float | None = None,
    muted: bool | None = None,
    fade_in_ms: int | None = None,
    fade_out_ms: int | None = None,
) -> StudioSession:
    track, _clip = _find_clip(session, clip_id)

    def update(candidate: StudioClip) -> StudioClip:
        if candidate.clip_id != clip_id:
            return candidate
        updated = replace(
            candidate,
            gain_db=(
                candidate.gain_db
                if gain_db is None
                else clamp_studio_clip_gain_db(gain_db)
            ),
            muted=candidate.muted if muted is None else bool(muted),
            fade_in_ms=(
                candidate.fade_in_ms
                if fade_in_ms is None
                else max(0, int(fade_in_ms))
            ),
            fade_out_ms=(
                candidate.fade_out_ms
                if fade_out_ms is None
                else max(0, int(fade_out_ms))
            ),
        )
        return _with_clamped_fades(updated)

    return _replace_track(
        session,
        track.track_id,
        lambda current: replace(current, clips=tuple(update(clip) for clip in current.clips)),
    )


def set_studio_clip_media(
    session: StudioSession,
    clip_id: str,
    settings: StudioMediaSettings,
) -> StudioSession:
    track, _clip = _find_clip(session, clip_id)
    if track.role != TRACK_VIDEO:
        raise StudioTimelineError("Media settings can only be changed on a media clip.")
    return _replace_clip(
        session,
        track.track_id,
        clip_id,
        lambda clip: replace(clip, media=settings),
    )


def _replace_track(session: StudioSession, track_id: str, update) -> StudioSession:
    _find_track(session, track_id)
    return replace(
        session,
        tracks=tuple(update(track) if track.track_id == track_id else track for track in session.tracks),
    )


def _replace_clip(session: StudioSession, track_id: str, clip_id: str, update) -> StudioSession:
    return _replace_track(
        session,
        track_id,
        lambda track: replace(
            track,
            clips=tuple(
                update(clip) if clip.clip_id == clip_id else clip for clip in track.clips
            ),
        ),
    )


def _find_track(session: StudioSession, track_id: str) -> StudioTrack:
    track = next((candidate for candidate in session.tracks if candidate.track_id == track_id), None)
    if track is None:
        raise StudioTimelineError(f"Unknown Studio track: {track_id}")
    return track


def _find_clip(session: StudioSession, clip_id: str) -> tuple[StudioTrack, StudioClip]:
    for track in session.tracks:
        clip = next((candidate for candidate in track.clips if candidate.clip_id == clip_id), None)
        if clip is not None:
            return track, clip
    raise StudioTimelineError(f"Unknown Studio clip: {clip_id}")


def _sorted_clips(clips) -> tuple[StudioClip, ...]:
    return tuple(sorted(clips, key=lambda clip: (clip.timeline_start_ms, clip.clip_id)))


def _with_clamped_fades(clip: StudioClip) -> StudioClip:
    fade_in = min(clip.duration_ms, max(0, int(clip.fade_in_ms)))
    fade_out = min(
        max(0, clip.duration_ms - fade_in),
        max(0, int(clip.fade_out_ms)),
    )
    return replace(clip, fade_in_ms=fade_in, fade_out_ms=fade_out)


def _track_accepts_asset(track: StudioTrack, asset: StudioAssetRef) -> bool:
    return (track.role == TRACK_VIDEO) == (asset.role == TRACK_VIDEO)
