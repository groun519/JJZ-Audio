from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.segment_review import SegmentCandidate, normalize_segment_status


TRAINING_MODE_FULL = "full"
TRAINING_MODE_CLIPS = "clips"
REVIEW_UNREVIEWED = "unreviewed"
REVIEW_EDITING = "editing"
REVIEW_READY = "ready"
HISTORY_LIMIT = 30

ClipRange = tuple[int, int]


@dataclass(frozen=True)
class ClipEditState:
    training_mode: str
    review_state: str
    ranges: tuple[ClipRange, ...] = ()
    segment_candidates: tuple[SegmentCandidate, ...] | None = None


@dataclass(frozen=True)
class ClipEditHistory:
    undo_states: tuple[ClipEditState, ...] = ()
    redo_states: tuple[ClipEditState, ...] = ()

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_states)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_states)

    def record(self, current: ClipEditState) -> "ClipEditHistory":
        return ClipEditHistory(_bounded(self.undo_states + (current,)), ())

    def undo(self, current: ClipEditState) -> tuple[ClipEditState | None, "ClipEditHistory"]:
        if not self.undo_states:
            return None, self
        target = self.undo_states[-1]
        history = ClipEditHistory(self.undo_states[:-1], _bounded(self.redo_states + (current,)))
        return target, history

    def redo(self, current: ClipEditState) -> tuple[ClipEditState | None, "ClipEditHistory"]:
        if not self.redo_states:
            return None, self
        target = self.redo_states[-1]
        history = ClipEditHistory(_bounded(self.undo_states + (current,)), self.redo_states[:-1])
        return target, history


def state_from_values(
    training_mode: object,
    review_state: object,
    ranges: tuple[ClipRange, ...],
    segment_candidates: tuple[SegmentCandidate, ...] | None = None,
) -> ClipEditState:
    mode = training_mode if training_mode in {TRAINING_MODE_FULL, TRAINING_MODE_CLIPS} else TRAINING_MODE_FULL
    review = review_state if review_state in {REVIEW_UNREVIEWED, REVIEW_EDITING, REVIEW_READY} else REVIEW_UNREVIEWED
    return ClipEditState(str(mode), str(review), ranges, segment_candidates)


def history_to_data(history: ClipEditHistory) -> dict[str, object]:
    return {
        "undo": [_state_to_data(state) for state in history.undo_states],
        "redo": [_state_to_data(state) for state in history.redo_states],
    }


def history_from_data(value: object) -> ClipEditHistory:
    if not isinstance(value, dict):
        return ClipEditHistory()
    undo = _states_from_data(value.get("undo"))
    redo = _states_from_data(value.get("redo"))
    return ClipEditHistory(_bounded(undo), _bounded(redo))


def _state_to_data(state: ClipEditState) -> dict[str, object]:
    data: dict[str, object] = {
        "training_mode": state.training_mode,
        "review_state": state.review_state,
        "ranges": [[start, end] for start, end in state.ranges],
    }
    if state.segment_candidates is not None:
        data["segment_candidates"] = [
            {
                "id": candidate.candidate_id,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "status": candidate.status,
            }
            for candidate in state.segment_candidates
        ]
    return data


def _states_from_data(value: object) -> tuple[ClipEditState, ...]:
    if not isinstance(value, list):
        return ()
    states: list[ClipEditState] = []
    for raw_state in value:
        if not isinstance(raw_state, dict):
            continue
        ranges = _ranges_from_data(raw_state.get("ranges"))
        states.append(
            state_from_values(
                raw_state.get("training_mode"),
                raw_state.get("review_state"),
                ranges,
                _segment_candidates_from_data(raw_state.get("segment_candidates"))
                if "segment_candidates" in raw_state
                else None,
            )
        )
    return tuple(states)


def _ranges_from_data(value: object) -> tuple[ClipRange, ...]:
    if not isinstance(value, list):
        return ()
    ranges: list[ClipRange] = []
    for raw_range in value:
        if not isinstance(raw_range, list) or len(raw_range) != 2:
            continue
        try:
            start, end = int(raw_range[0]), int(raw_range[1])
        except (TypeError, ValueError):
            continue
        if start >= 0 and end - start >= 100:
            ranges.append((start, end))
    return tuple(ranges)


def _segment_candidates_from_data(value: object) -> tuple[SegmentCandidate, ...]:
    if not isinstance(value, list):
        return ()
    candidates: list[SegmentCandidate] = []
    for raw_candidate in value:
        if not isinstance(raw_candidate, dict):
            continue
        try:
            candidate = SegmentCandidate(
                candidate_id=str(raw_candidate["id"]),
                start_ms=max(0, int(raw_candidate["start_ms"])),
                end_ms=max(0, int(raw_candidate["end_ms"])),
                status=normalize_segment_status(raw_candidate.get("status")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if candidate.candidate_id and candidate.duration_ms >= 100:
            candidates.append(candidate)
    return tuple(candidates)


def _bounded(states: tuple[ClipEditState, ...]) -> tuple[ClipEditState, ...]:
    return states[-HISTORY_LIMIT:]
