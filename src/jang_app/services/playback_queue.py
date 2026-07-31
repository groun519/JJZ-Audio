from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlaybackQueue:
    context: str
    source_id: str
    title: str
    paths: tuple[Path, ...]
    volumes: tuple[float, ...]
    duration_ms: int = 0

    def with_duration(self, duration_ms: int) -> PlaybackQueue:
        return PlaybackQueue(
            context=self.context,
            source_id=self.source_id,
            title=self.title,
            paths=self.paths,
            volumes=self.volumes,
            duration_ms=max(0, duration_ms),
        )

    def has_same_sources(self, other: PlaybackQueue | None) -> bool:
        if other is None:
            return False
        return self.context == other.context and _resolved_paths(self.paths) == _resolved_paths(other.paths)


def _resolved_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path.expanduser().resolve() for path in paths)
