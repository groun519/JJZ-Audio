from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.song_library import SongItem
from jang_app.services.work_scope import WorkTaskScope


def _song(song_id: str, *, kind: str = "source") -> SongItem:
    return SongItem(song_id, Path(f"{song_id}.wav"), kind=kind)


class WorkTaskScopeTests(unittest.TestCase):
    def test_is_current_matches_song_id(self) -> None:
        scope = WorkTaskScope("song-a")

        self.assertTrue(scope.is_current(_song("song-a")))
        self.assertFalse(scope.is_current(_song("song-b")))
        self.assertFalse(scope.is_current(None))


if __name__ == "__main__":
    unittest.main()
