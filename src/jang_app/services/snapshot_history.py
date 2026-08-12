from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Generic, Self, TypeVar


StateT = TypeVar("StateT")


@dataclass(frozen=True)
class SnapshotHistory(Generic[StateT]):
    """Bounded, immutable undo/redo history for value-based editor state."""

    undo_states: tuple[StateT, ...] = ()
    redo_states: tuple[StateT, ...] = ()
    history_limit: ClassVar[int] = 100

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_states)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_states)

    def record(self, current: StateT) -> Self:
        return type(self)(self._bounded((*self.undo_states, current)), ())

    def undo(self, current: StateT) -> tuple[StateT | None, Self]:
        if not self.undo_states:
            return None, self
        target = self.undo_states[-1]
        history = type(self)(
            self.undo_states[:-1],
            self._bounded((*self.redo_states, current)),
        )
        return target, history

    def redo(self, current: StateT) -> tuple[StateT | None, Self]:
        if not self.redo_states:
            return None, self
        target = self.redo_states[-1]
        history = type(self)(
            self._bounded((*self.undo_states, current)),
            self.redo_states[:-1],
        )
        return target, history

    def _bounded(self, states: tuple[StateT, ...]) -> tuple[StateT, ...]:
        return states[-self.history_limit :]
