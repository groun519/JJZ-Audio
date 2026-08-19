from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from jang_app.services.studio_session import StudioClip, StudioSession, StudioTrack
from jang_app.services.studio_timeline import (
    StudioTimelineError,
    resolve_studio_clip_position,
    resolve_studio_clip_trim,
)


SNAP_TARGET_CLIP_START = "clip_start"
SNAP_TARGET_CLIP_END = "clip_end"
SNAP_TARGET_PLAYHEAD = "playhead"
SNAP_TARGET_TIMELINE_START = "timeline_start"


@dataclass(frozen=True)
class StudioSnapTarget:
    position_ms: int
    kind: str
    track_id: str = ""
    clip_id: str = ""


@dataclass(frozen=True)
class StudioSnapIndex:
    targets: tuple[StudioSnapTarget, ...]
    positions_ms: tuple[int, ...]


@dataclass(frozen=True)
class StudioSnapResult:
    position_ms: int
    target: StudioSnapTarget | None = None
    moving_edge: str = "point"

    @property
    def snapped(self) -> bool:
        return self.target is not None


def build_studio_snap_index(session: StudioSession) -> StudioSnapIndex:
    """Build the immutable edit-point index reused during pointer movement."""
    targets = [StudioSnapTarget(0, SNAP_TARGET_TIMELINE_START)]
    for track in session.tracks:
        for clip in track.clips:
            targets.extend(
                (
                    StudioSnapTarget(
                        clip.timeline_start_ms,
                        SNAP_TARGET_CLIP_START,
                        track.track_id,
                        clip.clip_id,
                    ),
                    StudioSnapTarget(
                        clip.timeline_end_ms,
                        SNAP_TARGET_CLIP_END,
                        track.track_id,
                        clip.clip_id,
                    ),
                )
            )
    ordered = tuple(
        sorted(
            targets,
            key=lambda target: (
                target.position_ms,
                target.track_id,
                target.clip_id,
                target.kind,
            ),
        )
    )
    return StudioSnapIndex(ordered, tuple(target.position_ms for target in ordered))


def snap_studio_timeline_point(
    index: StudioSnapIndex,
    requested_ms: int,
    *,
    threshold_ms: int,
    preferred_track_id: str = "",
    playhead_ms: int | None = None,
    exclude_clip_id: str = "",
    minimum_ms: int = 0,
    maximum_ms: int | None = None,
) -> StudioSnapResult:
    requested = max(0, int(requested_ms))
    candidates = _point_candidates(
        index,
        requested,
        threshold_ms=max(0, int(threshold_ms)),
        preferred_track_id=preferred_track_id,
        playhead_ms=playhead_ms,
        exclude_clip_id=exclude_clip_id,
        minimum_ms=max(0, int(minimum_ms)),
        maximum_ms=maximum_ms,
    )
    if not candidates:
        return StudioSnapResult(requested)
    return candidates[0]


def snap_studio_clip_position(
    session: StudioSession,
    index: StudioSnapIndex,
    track_id: str,
    *,
    timeline_start_ms: int,
    duration_ms: int,
    threshold_ms: int,
    playhead_ms: int | None = None,
    exclude_clip_id: str = "",
) -> StudioSnapResult:
    """Snap either clip edge, accepting only candidates legal on the target track."""
    duration = int(duration_ms)
    if duration <= 0:
        raise StudioTimelineError("The source duration must be greater than zero.")
    requested = max(0, int(timeline_start_ms))
    candidates: list[tuple[tuple[int, int, int, int], StudioSnapResult]] = []
    for edge_order, (moving_edge, offset) in enumerate(
        (("start", 0), ("end", duration))
    ):
        anchor = requested + offset
        for point in _point_candidates(
            index,
            anchor,
            threshold_ms=max(0, int(threshold_ms)),
            preferred_track_id=track_id,
            playhead_ms=playhead_ms,
            exclude_clip_id=exclude_clip_id,
            minimum_ms=offset,
            maximum_ms=None,
        ):
            if point.target is None:
                continue
            candidate_start = point.position_ms - offset
            candidates.append(
                (
                    (
                        abs(point.target.position_ms - anchor),
                        _target_priority(point.target, track_id),
                        edge_order,
                        point.target.position_ms,
                    ),
                    StudioSnapResult(candidate_start, point.target, moving_edge),
                )
            )
    for _key, candidate in sorted(candidates, key=lambda item: item[0]):
        legal = resolve_studio_clip_position(
            session,
            track_id,
            timeline_start_ms=candidate.position_ms,
            duration_ms=duration,
            exclude_clip_id=exclude_clip_id,
        )
        if legal == candidate.position_ms:
            return candidate
    return StudioSnapResult(requested)


def snap_studio_clip_trim(
    session: StudioSession,
    index: StudioSnapIndex,
    clip_id: str,
    *,
    source_start_ms: int,
    source_end_ms: int,
    preserve_timeline_end: bool,
    threshold_ms: int,
    playhead_ms: int | None = None,
    maximum_source_end_ms: int | None = None,
) -> tuple[StudioClip, StudioSnapResult]:
    """Snap the actively trimmed edge and return the collision-safe preview clip."""
    track, clip = _find_clip(session, clip_id)
    requested_start = max(0, int(source_start_ms))
    requested_end = max(0, int(source_end_ms))
    if requested_end <= requested_start:
        raise StudioTimelineError("A clip must contain at least one millisecond of audio.")

    if preserve_timeline_end:
        moving_edge = "start"
        requested_position = (
            clip.timeline_start_ms + requested_start - clip.source_start_ms
        )
    else:
        moving_edge = "end"
        requested_position = (
            clip.timeline_start_ms + requested_end - clip.source_start_ms
        )

    candidates = _point_candidates(
        index,
        requested_position,
        threshold_ms=max(0, int(threshold_ms)),
        preferred_track_id=track.track_id,
        playhead_ms=playhead_ms,
        exclude_clip_id=clip_id,
        minimum_ms=0,
        maximum_ms=None,
    )
    for candidate in candidates:
        if candidate.target is None:
            continue
        if preserve_timeline_end:
            start = clip.source_start_ms + candidate.position_ms - clip.timeline_start_ms
            end = requested_end
        else:
            start = requested_start
            end = clip.source_start_ms + candidate.position_ms - clip.timeline_start_ms
        if (
            start < 0
            or end <= start
            or (maximum_source_end_ms is not None and end > maximum_source_end_ms)
        ):
            continue
        try:
            preview = resolve_studio_clip_trim(
                session,
                clip_id,
                source_start_ms=start,
                source_end_ms=end,
                preserve_timeline_end=preserve_timeline_end,
            )
        except StudioTimelineError:
            continue
        resolved_edge = (
            preview.timeline_start_ms if preserve_timeline_end else preview.timeline_end_ms
        )
        if resolved_edge == candidate.position_ms:
            return preview, StudioSnapResult(
                candidate.position_ms,
                candidate.target,
                moving_edge,
            )

    preview = resolve_studio_clip_trim(
        session,
        clip_id,
        source_start_ms=requested_start,
        source_end_ms=requested_end,
        preserve_timeline_end=preserve_timeline_end,
    )
    return preview, StudioSnapResult(requested_position)


def _point_candidates(
    index: StudioSnapIndex,
    requested_ms: int,
    *,
    threshold_ms: int,
    preferred_track_id: str,
    playhead_ms: int | None,
    exclude_clip_id: str,
    minimum_ms: int,
    maximum_ms: int | None,
) -> tuple[StudioSnapResult, ...]:
    lower = requested_ms - threshold_ms
    upper = requested_ms + threshold_ms
    left = bisect_left(index.positions_ms, lower)
    right = bisect_right(index.positions_ms, upper)
    targets = list(index.targets[left:right])
    if playhead_ms is not None and lower <= int(playhead_ms) <= upper:
        targets.append(StudioSnapTarget(int(playhead_ms), SNAP_TARGET_PLAYHEAD))

    valid = (
        target
        for target in targets
        if (not exclude_clip_id or target.clip_id != exclude_clip_id)
        and target.position_ms >= minimum_ms
        and (maximum_ms is None or target.position_ms <= maximum_ms)
    )
    ordered = sorted(
        valid,
        key=lambda target: (
            abs(target.position_ms - requested_ms),
            _target_priority(target, preferred_track_id),
            target.position_ms,
            target.track_id,
            target.clip_id,
        ),
    )
    return tuple(StudioSnapResult(target.position_ms, target) for target in ordered)


def _target_priority(target: StudioSnapTarget, preferred_track_id: str) -> int:
    if target.track_id and target.track_id == preferred_track_id:
        return 0
    if target.kind == SNAP_TARGET_PLAYHEAD:
        return 1
    if target.track_id:
        return 2
    return 3


def _find_clip(session: StudioSession, clip_id: str) -> tuple[StudioTrack, StudioClip]:
    for track in session.tracks:
        for clip in track.clips:
            if clip.clip_id == clip_id:
                return track, clip
    raise StudioTimelineError(f"Studio clip was not found: {clip_id}")
