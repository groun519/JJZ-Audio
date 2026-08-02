from __future__ import annotations

from dataclasses import dataclass


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
) -> ClipEditState:
    mode = training_mode if training_mode in {TRAINING_MODE_FULL, TRAINING_MODE_CLIPS} else TRAINING_MODE_FULL
    review = review_state if review_state in {REVIEW_UNREVIEWED, REVIEW_EDITING, REVIEW_READY} else REVIEW_UNREVIEWED
    return ClipEditState(str(mode), str(review), ranges)


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
    return {
        "training_mode": state.training_mode,
        "review_state": state.review_state,
        "ranges": [[start, end] for start, end in state.ranges],
    }


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


def _bounded(states: tuple[ClipEditState, ...]) -> tuple[ClipEditState, ...]:
    return states[-HISTORY_LIMIT:]
