from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set
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
        self._sound_sets_by_job_dir: dict[Path, OutputSoundSet] = {}
        self._cache_sound_sets(self._sound_sets)
        if sound_set is not None:
            self.remember_sound_set(sound_set)

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
        if sound_set is not None:
            self.remember_sound_set(sound_set)
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
        self._cache_sound_sets(self._sound_sets)
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
        cached = self._sound_sets_by_job_dir.get(resolved)
        if cached is not None:
            return cached
        for sound_set in self._sound_sets:
            if _same_job_dir(sound_set.job_dir, resolved):
                return sound_set
        return None

    def remember_sound_set(self, sound_set: OutputSoundSet) -> OutputSoundSet:
        resolved = sound_set.job_dir.expanduser().resolve()
        self._sound_sets_by_job_dir[resolved] = sound_set
        self._sound_sets = tuple(
            sound_set if _same_job_dir(existing.job_dir, resolved) else existing
            for existing in self._sound_sets
        )
        return sound_set

    def load_sound_set(
        self,
        job_dir: Path,
        output_root: Path,
        *,
        reload: bool = False,
        loader: Callable[[Path, Path], OutputSoundSet | None] = load_output_sound_set,
    ) -> OutputSoundSet | None:
        resolved = job_dir.expanduser().resolve()
        if not reload:
            cached = self._sound_sets_by_job_dir.get(resolved)
            if cached is not None:
                return cached
        sound_set = loader(job_dir, output_root)
        if sound_set is None:
            self._sound_sets_by_job_dir.pop(resolved, None)
            return None
        return self.remember_sound_set(sound_set)

    def output_available(
        self,
        job_dir: Path | None,
        output_root: Path,
        *,
        loader: Callable[[Path, Path], OutputSoundSet | None] = load_output_sound_set,
    ) -> bool:
        if job_dir is None:
            return False
        return self.load_sound_set(job_dir, output_root, loader=loader) is not None

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

    def _cache_sound_sets(self, sound_sets: Sequence[OutputSoundSet]) -> None:
        current_selection = (
            self._sound_set.job_dir.expanduser().resolve()
            if self._sound_set is not None
            else None
        )
        catalog_keys = {
            sound_set.job_dir.expanduser().resolve()
            for sound_set in sound_sets
        }
        self._sound_sets_by_job_dir = {
            job_dir: cached
            for job_dir, cached in self._sound_sets_by_job_dir.items()
            if job_dir in catalog_keys or job_dir == current_selection
        }
        for sound_set in sound_sets:
            self.remember_sound_set(sound_set)


def _same_job_dir(first: Path, second: Path) -> bool:
    return first.expanduser().resolve() == second.expanduser().resolve()
