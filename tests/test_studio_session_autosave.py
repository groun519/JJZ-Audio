from __future__ import annotations

import unittest
from threading import Event, Timer
from time import monotonic

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_session_autosave import StudioSessionAutosave
from jang_app.services.studio_session import StudioSession, StudioTrackState


class StudioSessionAutosaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_debounces_same_song_and_flushes_all_songs_in_order(self) -> None:
        saved: list[tuple[str, StudioSession, tuple[object, ...]]] = []
        autosave = StudioSessionAutosave(
            lambda song_id, session, assets: saved.append((song_id, session, assets))
        )
        first = StudioSession(original_vocal=StudioTrackState(volume_percent=110))
        latest = StudioSession(original_vocal=StudioTrackState(volume_percent=140))
        second_song = StudioSession(instrumental=StudioTrackState(muted=True))
        first_assets = (object(),)
        latest_assets = (object(),)
        second_assets = (object(),)

        autosave.queue("song-1", first, first_assets)
        autosave.queue("song-1", latest, latest_assets)
        self.assertEqual(saved, [])

        autosave.queue("song-2", second_song, second_assets)
        self.assertEqual(saved, [])

        autosave.flush()
        self.assertEqual(
            saved,
            [
                ("song-1", latest, latest_assets),
                ("song-2", second_song, second_assets),
            ],
        )

    def test_debounced_save_work_runs_outside_the_ui_thread(self) -> None:
        started = Event()
        release = Event()
        saved: list[str] = []

        def slow_save(
            song_id: str,
            _session: StudioSession,
            _assets: tuple[object, ...],
        ) -> None:
            started.set()
            release.wait(timeout=2)
            saved.append(song_id)

        autosave = StudioSessionAutosave(slow_save, delay_ms=0)
        before = monotonic()
        autosave.queue("song-1", StudioSession(), ())
        QTest.qWait(20)

        self.assertTrue(started.is_set())
        self.assertLess(monotonic() - before, 0.25)
        self.assertEqual(saved, [])

        release.set()
        for _ in range(20):
            if saved:
                break
            QTest.qWait(10)
        self.assertEqual(saved, ["song-1"])

    def test_reports_save_failure_and_retries_the_pending_state(self) -> None:
        attempts = 0
        saved: list[str] = []

        def fail(
            song_id: str,
            _session: StudioSession,
            _assets: tuple[object, ...],
        ) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("disk unavailable")
            saved.append(song_id)

        autosave = StudioSessionAutosave(fail)
        failed = QSignalSpy(autosave.save_failed)
        autosave.queue("song-1", StudioSession(), ())

        self.assertFalse(autosave.flush())
        self.assertTrue(autosave.flush())

        self.assertEqual(failed.count(), 1)
        self.assertEqual(failed.at(0)[0], "disk unavailable")
        self.assertEqual(saved, ["song-1"])

    def test_superseded_background_save_does_not_report_stale_state_as_saved(self) -> None:
        started = Event()
        release = Event()

        def slow_save(
            _song_id: str,
            session: StudioSession,
            _assets: tuple[object, ...],
        ) -> None:
            if session.original_vocal.volume_percent == 110:
                started.set()
                release.wait(timeout=2)

        autosave = StudioSessionAutosave(slow_save, delay_ms=0)
        states = QSignalSpy(autosave.save_state_changed)
        autosave.queue(
            "song-1",
            StudioSession(original_vocal=StudioTrackState(volume_percent=110)),
            (),
        )
        QTest.qWait(20)
        self.assertTrue(started.is_set())
        autosave.queue(
            "song-1",
            StudioSession(original_vocal=StudioTrackState(volume_percent=140)),
            (),
        )

        release.set()
        for _ in range(40):
            if any(states.at(index)[1] == "saved" for index in range(states.count())):
                break
            QTest.qWait(10)

        state_names = [states.at(index)[1] for index in range(states.count())]
        self.assertEqual(state_names.count("saved"), 1)
        self.assertGreaterEqual(state_names.count("saving"), 2)

    def test_discard_prevents_a_removed_session_from_being_recreated(self) -> None:
        saved: list[tuple[str, StudioSession, tuple[object, ...]]] = []
        autosave = StudioSessionAutosave(
            lambda song_id, session, assets: saved.append((song_id, session, assets))
        )
        autosave.queue("song-1", StudioSession(), ())

        autosave.discard("song-1")
        autosave.flush()

        self.assertEqual(saved, [])

    def test_discard_waits_for_an_inflight_save_before_deletion_can_continue(self) -> None:
        started = Event()
        release = Event()
        order: list[str] = []

        def held_save(
            _song_id: str,
            _session: StudioSession,
            _assets: tuple[object, ...],
        ) -> None:
            started.set()
            release.wait(2)
            order.append("save-finished")

        autosave = StudioSessionAutosave(held_save, delay_ms=0)
        states = QSignalSpy(autosave.save_state_changed)
        autosave.queue("song-1", StudioSession(), ())
        QTest.qWait(20)
        self.assertTrue(started.is_set())

        timer = Timer(0.05, release.set)
        timer.start()
        autosave.discard("song-1")
        order.append("delete-started")
        timer.join()

        self.assertEqual(order, ["save-finished", "delete-started"])
        self.assertNotIn(
            "saved",
            [states.at(index)[1] for index in range(states.count())],
        )


if __name__ == "__main__":
    unittest.main()
