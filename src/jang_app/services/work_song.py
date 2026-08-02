from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import WORK_SONG_FILE
from jang_app.services.managed_files import write_json_atomic


WORK_SONG_VERSION = 1


@dataclass(frozen=True)
class WorkSongState:
    song_id: str = ""


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
