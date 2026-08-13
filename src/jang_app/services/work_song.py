from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jang_app.config import WORK_SONG_FILE
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.song_library import SongItem


WORK_SONG_VERSION = 1


@dataclass(frozen=True)
class WorkSongState:
    song_id: str = ""


@dataclass(frozen=True)
class WorkSongCapabilities:
    can_separate: bool = False
    can_attach_source: bool = False
    can_convert: bool = False
    can_export: bool = False


@dataclass(frozen=True)
class WorkSongRoute:
    action: Literal["ignore", "sync_selector", "clear", "select", "load_output"]
    song: SongItem | None = None


class WorkSongStore:
    def __init__(self, path: Path = WORK_SONG_FILE) -> None:
        self.path = path.expanduser().resolve()

    def load(self) -> WorkSongState:
        if not self.path.is_file():
            return WorkSongState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return WorkSongState()
        if not isinstance(data, dict) or data.get("version") != WORK_SONG_VERSION:
            return WorkSongState()
        song_id = data.get("song_id")
        return WorkSongState(song_id.strip() if isinstance(song_id, str) else "")

    def save(self, song_id: str) -> Path:
        write_json_atomic(
            self.path,
            {
                "version": WORK_SONG_VERSION,
                "song_id": song_id.strip(),
            },
        )
        return self.path


class WorkSongSession:
    def __init__(
        self,
        store: WorkSongStore | None = None,
        *,
        item: SongItem | None = None,
        ready: bool = False,
    ) -> None:
        self._store = store or WorkSongStore()
        self._item = item
        self._ready = bool(ready)

    @property
    def item(self) -> SongItem | None:
        return self._item

    @property
    def source_item(self) -> SongItem | None:
        if self._item is None or self._item.kind != "source":
            return None
        return self._item

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def selected_id(self) -> str:
        return self._item.id if self._item is not None else ""

    @property
    def title(self) -> str:
        return self._item.title if self._item is not None else ""

    def has_selection(self) -> bool:
        return self._item is not None

    def is_selected(self, song_id: str) -> bool:
        return bool(song_id) and self._item is not None and self._item.id == song_id

    def capabilities(self, *, output_available: bool) -> WorkSongCapabilities:
        return build_work_song_capabilities(self._item, output_available=output_available)

    def assign(self, item: SongItem | None, *, persist: bool = True) -> SongItem | None:
        self._item = item
        if persist and self._ready:
            self._store.save(item.id if item is not None else "")
        return self._item

    def refresh(self, items_by_id: Mapping[str, SongItem]) -> SongItem | None:
        if self._item is None:
            return self.assign(None, persist=False)
        return self.assign(items_by_id.get(self._item.id), persist=False)

    def restore_route(self, items_by_id: Mapping[str, SongItem]) -> WorkSongRoute:
        state = self._store.load()
        self._ready = True
        if not state.song_id:
            return WorkSongRoute("clear")
        song = items_by_id.get(state.song_id)
        if song is None:
            try:
                self._store.save("")
            except OSError:
                pass
            return WorkSongRoute("clear")
        return self._route_for_song(song)

    def navigation_route(
        self,
        song_id: str,
        items_by_id: Mapping[str, SongItem],
        *,
        load_in_progress: bool,
    ) -> WorkSongRoute:
        if load_in_progress:
            return WorkSongRoute("sync_selector")
        if not song_id:
            return WorkSongRoute("clear")
        song = items_by_id.get(song_id)
        if song is None:
            return WorkSongRoute("sync_selector")
        return self._route_for_song(song)

    def toggle_route(
        self,
        song_id: str,
        items_by_id: Mapping[str, SongItem],
        *,
        load_in_progress: bool,
    ) -> WorkSongRoute:
        if load_in_progress:
            return WorkSongRoute("ignore")
        song = items_by_id.get(song_id)
        if song is None:
            return WorkSongRoute("ignore")
        if self.is_selected(song_id):
            return WorkSongRoute("clear")
        return self._route_for_song(song)

    def _route_for_song(self, song: SongItem) -> WorkSongRoute:
        if getattr(song, "output_job_dir", None) is not None:
            return WorkSongRoute("load_output", song)
        return WorkSongRoute("select", song)


def build_work_song_capabilities(
    item: SongItem | None,
    *,
    output_available: bool,
) -> WorkSongCapabilities:
    has_output = item is not None and output_available
    return WorkSongCapabilities(
        can_separate=item is not None and item.kind == "source",
        can_attach_source=item is not None and item.kind == "output",
        can_convert=has_output,
        can_export=has_output,
    )
