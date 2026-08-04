from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter


Clock = Callable[[], float]


@dataclass(frozen=True)
class StartupMark:
    name: str
    elapsed_ms: float


class StartupTimeline:
    def __init__(
        self,
        started_at: float | None = None,
        *,
        clock: Clock = perf_counter,
    ) -> None:
        self._clock = clock
        self._started_at = clock() if started_at is None else started_at
        self._marks: list[StartupMark] = []

    @property
    def marks(self) -> tuple[StartupMark, ...]:
        return tuple(self._marks)

    def mark(self, name: str) -> StartupMark:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Startup mark name is required")
        if any(mark.name == normalized for mark in self._marks):
            raise ValueError(f"Duplicate startup mark: {normalized}")

        elapsed_ms = max(0.0, (self._clock() - self._started_at) * 1000)
        mark = StartupMark(normalized, elapsed_ms)
        self._marks.append(mark)
        return mark

    def summary(self) -> str:
        if not self._marks:
            return "Startup timing | no marks"
        timings = " | ".join(
            f"{mark.name}={mark.elapsed_ms:.1f}ms" for mark in self._marks
        )
        return f"Startup timing | {timings} | total={self._marks[-1].elapsed_ms:.1f}ms"
