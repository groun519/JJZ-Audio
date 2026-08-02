from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.song_library import SongItem
from jang_app.services.work_scope import WorkTaskScope, build_work_song_capabilities


def _song(song_id: str, *, kind: str = "source") -> SongItem:
    return SongItem(song_id, Path(f"{song_id}.wav"), kind=kind)


class WorkSongCapabilitiesTests(unittest.TestCase):
    def test_source_without_output_can_only_separate(self) -> None:
        capabilities = build_work_song_capabilities(_song("source"), output_available=False)

        self.assertTrue(capabilities.can_separate)
        self.assertFalse(capabilities.can_convert)
        self.assertFalse(capabilities.can_edit_studio)
        self.assertFalse(capabilities.can_export)

    def test_loaded_output_enables_downstream_workflows(self) -> None:
        capabilities = build_work_song_capabilities(_song("output", kind="output"), output_available=True)

        self.assertFalse(capabilities.can_separate)
        self.assertTrue(capabilities.can_convert)
        self.assertTrue(capabilities.can_edit_studio)
        self.assertTrue(capabilities.can_export)


class WorkTaskScopeTests(unittest.TestCase):
    def test_completed_output_is_selected_only_while_task_song_is_current(self) -> None:
        scope = WorkTaskScope("song-a")
        completed = Path("song-a-output")

        current_target = scope.output_refresh_target(completed, _song("song-a"), None)
        switched_target = scope.output_refresh_target(completed, _song("song-b"), Path("song-b-output"))
        empty_target = scope.output_refresh_target(completed, _song("song-b"), None)

        self.assertEqual(current_target.preferred_job_dir, completed)
        self.assertTrue(current_target.select_fallback)
        self.assertEqual(switched_target.preferred_job_dir, Path("song-b-output"))
        self.assertTrue(switched_target.select_fallback)
        self.assertIsNone(empty_target.preferred_job_dir)
        self.assertFalse(empty_target.select_fallback)


if __name__ == "__main__":
    unittest.main()
