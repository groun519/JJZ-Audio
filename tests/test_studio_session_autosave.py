from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_session_autosave import StudioSessionAutosave
from jang_app.services.studio_session import StudioSession, StudioTrackState


class StudioSessionAutosaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_debounces_same_song_and_flushes_before_song_changes(self) -> None:
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
        self.assertEqual(saved, [("song-1", latest, latest_assets)])

        autosave.flush()
        self.assertEqual(
            saved,
            [
                ("song-1", latest, latest_assets),
                ("song-2", second_song, second_assets),
            ],
        )

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

    def test_discard_prevents_a_removed_session_from_being_recreated(self) -> None:
        saved: list[tuple[str, StudioSession, tuple[object, ...]]] = []
        autosave = StudioSessionAutosave(
            lambda song_id, session, assets: saved.append((song_id, session, assets))
        )
        autosave.queue("song-1", StudioSession(), ())

        autosave.discard("song-1")
        autosave.flush()

        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
