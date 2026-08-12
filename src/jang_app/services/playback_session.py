from __future__ import annotations

from dataclasses import dataclass, replace

from jang_app.services.playback_queue import PlaybackQueue


@dataclass(frozen=True)
class PlaybackStateChange:
    previous_queue: PlaybackQueue | None
    current_queue: PlaybackQueue | None
    position_ms: int


class PlaybackSession:
    def __init__(
        self,
        queue: PlaybackQueue | None = None,
        position_ms: int = 0,
        resume_positions: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self._queue = queue
        self._position_ms = (
            _clamp_position(position_ms, queue.duration_ms)
            if queue is not None
            else max(0, int(position_ms))
        )
        self._resume_positions = resume_positions if resume_positions is not None else {}

    @property
    def queue(self) -> PlaybackQueue | None:
        return self._queue

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def resume_positions(self) -> dict[tuple[str, str], int]:
        return self._resume_positions

    def current_context(self) -> str:
        return self._queue.context if self._queue is not None else ""

    def is_context(self, context: str) -> bool:
        return self.current_context() == context

    def set_queue(
        self,
        queue: PlaybackQueue | None,
        *,
        position_ms: int = 0,
        previous_position_ms: int | None = None,
    ) -> PlaybackStateChange:
        previous_queue = self._queue
        if previous_queue is not None and not _same_route(previous_queue, queue):
            self._remember_queue(
                previous_queue,
                previous_position_ms
                if previous_position_ms is not None
                else self._position_ms,
            )
        self._queue = queue
        self._position_ms = _clamp_to_queue(queue, position_ms)
        return PlaybackStateChange(previous_queue, self._queue, self._position_ms)

    def refresh_queue(
        self,
        queue: PlaybackQueue | None,
        *,
        position_ms: int,
    ) -> PlaybackStateChange:
        previous_queue = self._queue
        self._queue = queue
        self._position_ms = _clamp_to_queue(queue, position_ms)
        return PlaybackStateChange(previous_queue, self._queue, self._position_ms)

    def stop(self) -> PlaybackStateChange:
        previous_queue = self._queue
        self._position_ms = 0
        return PlaybackStateChange(previous_queue, self._queue, self._position_ms)

    def clear_queue(self) -> PlaybackStateChange:
        previous_queue = self._queue
        self._queue = None
        self._position_ms = 0
        return PlaybackStateChange(previous_queue, self._queue, self._position_ms)

    def suspend(self, current_position_ms: int) -> PlaybackStateChange:
        if self._queue is not None:
            self._remember_queue(self._queue, current_position_ms)
        return self.clear_queue()

    def set_position_ms(self, position_ms: int) -> int:
        self._position_ms = _clamp_to_queue(self._queue, position_ms)
        return self._position_ms

    def resume_position(self, queue: PlaybackQueue) -> int:
        return _clamp_position(
            self._resume_positions.get((queue.context, queue.source_id), 0),
            queue.duration_ms,
        )

    def remember_position(
        self,
        context: str,
        source_id: str,
        position_ms: int,
        *,
        duration_ms: int | None = None,
    ) -> int:
        value = _clamp_position(position_ms, duration_ms)
        self._resume_positions[(context, source_id)] = value
        return value

    def pop_resume_position(self, context: str, source_id: str) -> int | None:
        return self._resume_positions.pop((context, source_id), None)

    def replace_title(self, context: str, source_id: str, title: str) -> PlaybackQueue | None:
        if self._queue is None or self._queue.context != context or self._queue.source_id != source_id:
            return None
        self._queue = replace(self._queue, title=title)
        return self._queue

    def _remember_queue(self, queue: PlaybackQueue, position_ms: int) -> None:
        self._resume_positions[(queue.context, queue.source_id)] = _clamp_position(
            position_ms,
            queue.duration_ms,
        )


def _same_route(left: PlaybackQueue | None, right: PlaybackQueue | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.context == right.context and left.source_id == right.source_id


def _clamp_to_queue(queue: PlaybackQueue | None, position_ms: int) -> int:
    duration_ms = queue.duration_ms if queue is not None else None
    return _clamp_position(position_ms, duration_ms)


def _clamp_position(position_ms: int, duration_ms: int | None) -> int:
    value = max(0, int(position_ms))
    if duration_ms is None:
        return value
    return min(value, max(0, int(duration_ms)))
