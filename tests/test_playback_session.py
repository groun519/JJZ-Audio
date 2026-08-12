from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.playback_queue import PlaybackQueue
from jang_app.services.playback_session import PlaybackSession


class PlaybackSessionTests(unittest.TestCase):
    def test_set_queue_caches_previous_route_position(self) -> None:
        previous = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Song 1",
            paths=(Path("song-1.wav"),),
            volumes=(1.0,),
            duration_ms=90_000,
        )
        current = PlaybackQueue(
            context="output",
            source_id="job-2",
            title="Output",
            paths=(Path("job-2.wav"),),
            volumes=(1.0,),
            duration_ms=60_000,
        )
        session = PlaybackSession(previous, position_ms=12_500)

        session.set_queue(current, position_ms=1_000, previous_position_ms=15_000)

        self.assertEqual(session.resume_position(previous), 15_000)
        self.assertIs(session.queue, current)
        self.assertEqual(session.position_ms, 1_000)

    def test_refresh_queue_replaces_active_queue_without_rewriting_resume_cache(self) -> None:
        previous = PlaybackQueue(
            context="output",
            source_id="job-1",
            title="Before",
            paths=(Path("before.wav"),),
            volumes=(1.0,),
            duration_ms=30_000,
        )
        refreshed = PlaybackQueue(
            context="output",
            source_id="job-1",
            title="After",
            paths=(Path("after.wav"),),
            volumes=(0.8,),
            duration_ms=45_000,
        )
        session = PlaybackSession(
            previous,
            position_ms=3_000,
            resume_positions={("output", "job-1"): 9_000},
        )

        session.refresh_queue(refreshed, position_ms=4_500)

        self.assertIs(session.queue, refreshed)
        self.assertEqual(session.position_ms, 4_500)
        self.assertEqual(session.resume_position(refreshed), 9_000)

    def test_suspend_caches_current_position_and_clears_queue(self) -> None:
        queue = PlaybackQueue(
            context="library_asset",
            source_id=str(Path("mix.wav")),
            title="mix.wav",
            paths=(Path("mix.wav"),),
            volumes=(1.0,),
            duration_ms=42_000,
        )
        session = PlaybackSession(queue, position_ms=5_000)

        session.suspend(17_500)

        self.assertIsNone(session.queue)
        self.assertEqual(session.position_ms, 0)
        self.assertEqual(
            session.resume_positions[("library_asset", str(Path("mix.wav")))],
            17_500,
        )

    def test_replace_title_updates_only_matching_active_route(self) -> None:
        queue = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Old",
            paths=(Path("song.wav"),),
            volumes=(1.0,),
            duration_ms=10_000,
        )
        session = PlaybackSession(queue, position_ms=500)

        updated = session.replace_title("library", "song-1", "New")
        ignored = session.replace_title("export", "song-1", "Other")

        self.assertIsNotNone(updated)
        self.assertEqual(session.queue.title, "New")
        self.assertIsNone(ignored)


if __name__ == "__main__":
    unittest.main()
