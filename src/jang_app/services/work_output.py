from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongItem


@dataclass(frozen=True)
class OutputRefreshTarget:
    preferred_job_dir: Path | None
    select_fallback: bool


@dataclass(frozen=True)
class OutputSelection:
    sound_set: OutputSoundSet | None
    selected_index: int = -1


class WorkOutputSession:
    def __init__(
        self,
        sound_set: OutputSoundSet | None = None,
        *,
        sound_sets: Sequence[OutputSoundSet] = (),
    ) -> None:
        self._sound_set = sound_set
        self._sound_sets = tuple(sound_sets)

    @property
    def sound_set(self) -> OutputSoundSet | None:
        return self._sound_set

    @property
    def sound_sets(self) -> tuple[OutputSoundSet, ...]:
        return self._sound_sets

    @property
    def job_dir(self) -> Path | None:
        return self._sound_set.job_dir if self._sound_set is not None else None

    def assign(self, sound_set: OutputSoundSet | None) -> OutputSoundSet | None:
        self._sound_set = sound_set
        return self._sound_set

    def refresh_target(
        self,
        task_song_id: str,
        completed_job_dir: Path,
        current_item: SongItem | None,
    ) -> OutputRefreshTarget:
        if current_item is not None and current_item.id == task_song_id:
            return OutputRefreshTarget(completed_job_dir, True)
        current_output_dir = self.job_dir
        return OutputRefreshTarget(current_output_dir, current_output_dir is not None)

    def refresh_catalog(
        self,
        sound_sets: Sequence[OutputSoundSet],
        preferred_job_dir: Path | None = None,
        *,
        select_fallback: bool = True,
    ) -> OutputSelection:
        self._sound_sets = tuple(sound_sets)
        selection = self.selection_for_refresh(
            self._sound_sets,
            preferred_job_dir=preferred_job_dir,
            select_fallback=select_fallback,
        )
        self.assign(selection.sound_set)
        return selection

    def selection_for_refresh(
        self,
        sound_sets: Sequence[OutputSoundSet],
        preferred_job_dir: Path | None = None,
        *,
        select_fallback: bool = True,
    ) -> OutputSelection:
        if not sound_sets:
            return OutputSelection(None, -1)
        if preferred_job_dir is None and not select_fallback:
            return OutputSelection(None, -1)
        preferred_index = 0
        if preferred_job_dir is not None:
            resolved = preferred_job_dir.expanduser().resolve()
            for index, sound_set in enumerate(sound_sets):
                if _same_job_dir(sound_set.job_dir, resolved):
                    preferred_index = index
                    break
        return OutputSelection(sound_sets[preferred_index], preferred_index)

    def sound_set_for_job(self, job_dir: Path) -> OutputSoundSet | None:
        resolved = job_dir.expanduser().resolve()
        for sound_set in self._sound_sets:
            if _same_job_dir(sound_set.job_dir, resolved):
                return sound_set
        return None

    def selected_index_for_job(self, job_dir: Path) -> int:
        resolved = job_dir.expanduser().resolve()
        for index, sound_set in enumerate(self._sound_sets):
            if _same_job_dir(sound_set.job_dir, resolved):
                return index
        return -1

    def matches_work_item(self, item: SongItem | None) -> bool:
        if item is None or item.output_job_dir is None or self._sound_set is None:
            return False
        return _same_job_dir(item.output_job_dir, self._sound_set.job_dir)

    def linked_output_item(
        self,
        items_by_id: Mapping[str, SongItem],
        *,
        current_source_item: SongItem | None = None,
    ) -> SongItem | None:
        if current_source_item is not None or self._sound_set is None:
            return None
        resolved = self._sound_set.job_dir.expanduser().resolve()
        for item in items_by_id.values():
            if item.output_job_dir is None:
                continue
            if _same_job_dir(item.output_job_dir, resolved):
                return item
        return None


def _same_job_dir(first: Path, second: Path) -> bool:
    return first.expanduser().resolve() == second.expanduser().resolve()
