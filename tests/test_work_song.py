from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.song_library import SongItem
from jang_app.services.work_song import (
    WorkSongSession,
    WorkSongState,
    WorkSongStore,
    build_work_song_capabilities,
)


def _song(song_id: str, *, kind: str = "source", output_job_dir: Path | None = None) -> SongItem:
    return SongItem(song_id, Path(f"{song_id}.wav"), kind=kind, output_job_dir=output_job_dir)


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


class WorkSongCapabilitiesTests(unittest.TestCase):
    def test_source_without_output_can_only_separate(self) -> None:
        capabilities = build_work_song_capabilities(_song("source"), output_available=False)

        self.assertTrue(capabilities.can_separate)
        self.assertFalse(capabilities.can_convert)
        self.assertFalse(capabilities.can_export)

    def test_loaded_output_enables_downstream_workflows(self) -> None:
        capabilities = build_work_song_capabilities(
            _song("output", kind="output"),
            output_available=True,
        )

        self.assertFalse(capabilities.can_separate)
        self.assertTrue(capabilities.can_attach_source)
        self.assertTrue(capabilities.can_convert)
        self.assertTrue(capabilities.can_export)

    def test_source_with_existing_output_can_be_separated_again(self) -> None:
        capabilities = build_work_song_capabilities(_song("source"), output_available=True)

        self.assertTrue(capabilities.can_separate)
        self.assertFalse(capabilities.can_attach_source)


class WorkSongSessionTests(unittest.TestCase):
    def test_assign_persists_only_after_session_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkSongStore(Path(temporary) / "work_song.json")
            session = WorkSongSession(store)
            song = _song("song-1")

            session.assign(song)
            self.assertEqual(store.load(), WorkSongState())

            session.restore_route({})
            session.assign(song)
            self.assertEqual(store.load(), WorkSongState("song-1"))

    def test_navigation_route_prefers_output_load_when_song_has_output(self) -> None:
        session = WorkSongSession()
        song = _song("song-1", output_job_dir=Path("output/job"))

        route = session.navigation_route(
            "song-1",
            {"song-1": song},
            load_in_progress=False,
        )

        self.assertEqual(route.action, "load_output")
        self.assertIs(route.song, song)

    def test_toggle_route_clears_when_current_song_is_selected_again(self) -> None:
        song = _song("song-1")
        session = WorkSongSession(item=song)

        route = session.toggle_route(
            "song-1",
            {"song-1": song},
            load_in_progress=False,
        )

        self.assertEqual(route.action, "clear")

    def test_restore_route_clears_missing_saved_song_and_marks_session_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkSongStore(Path(temporary) / "work_song.json")
            store.save("missing-song")
            session = WorkSongSession(store)

            route = session.restore_route({})

            self.assertEqual(route.action, "clear")
            self.assertTrue(session.ready)
            self.assertEqual(store.load(), WorkSongState())

    def test_restore_route_uses_output_load_for_source_song_with_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkSongStore(Path(temporary) / "work_song.json")
            song = _song("song-1", output_job_dir=Path("output/job"))
            store.save(song.id)
            session = WorkSongSession(store)

            route = session.restore_route({song.id: song})

            self.assertEqual(route.action, "load_output")
            self.assertIs(route.song, song)


if __name__ == "__main__":
    unittest.main()
