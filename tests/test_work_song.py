from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.work_song import WorkSongState, WorkSongStore


class WorkSongStoreTests(unittest.TestCase):
    def test_selected_song_id_is_saved_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings" / "work_song.json"
            store = WorkSongStore(path)

            saved_path = store.save("  song-123  ")

            self.assertEqual(saved_path, path.resolve())
            self.assertEqual(store.load(), WorkSongState("song-123"))
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_missing_invalid_or_unsupported_state_uses_no_work_song(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "work_song.json"
            store = WorkSongStore(path)
            self.assertEqual(store.load(), WorkSongState())

            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(store.load(), WorkSongState())

            path.write_text(json.dumps({"version": 99, "song_id": "song-1"}), encoding="utf-8")
            self.assertEqual(store.load(), WorkSongState())

    def test_clearing_the_work_song_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkSongStore(Path(temporary) / "work_song.json")
            store.save("song-1")
            store.save("")
            self.assertEqual(store.load(), WorkSongState())


if __name__ == "__main__":
    unittest.main()
