from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jang_app.services.song_library import SongItem


@dataclass(frozen=True)
class OutputRefreshTarget:
    preferred_job_dir: Path | None
    select_fallback: bool


@dataclass(frozen=True)
class WorkTaskScope:
    song_id: str

    def is_current(self, item: SongItem | None) -> bool:
        return item is not None and item.id == self.song_id

    def output_refresh_target(
        self,
        completed_job_dir: Path,
        current_item: SongItem | None,
        current_output_dir: Path | None,
    ) -> OutputRefreshTarget:
        if self.is_current(current_item):
            return OutputRefreshTarget(completed_job_dir, True)
        return OutputRefreshTarget(current_output_dir, current_output_dir is not None)
