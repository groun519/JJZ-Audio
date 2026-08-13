from __future__ import annotations

from dataclasses import dataclass

from jang_app.services.song_library import SongItem


@dataclass(frozen=True)
class WorkTaskScope:
    song_id: str

    def is_current(self, item: SongItem | None) -> bool:
        return item is not None and item.id == self.song_id
