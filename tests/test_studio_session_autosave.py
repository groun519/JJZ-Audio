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
        saved: list[tuple[str, StudioSession]] = []
        autosave = StudioSessionAutosave(lambda song_id, session: saved.append((song_id, session)))
        first = StudioSession(original_vocal=StudioTrackState(volume_percent=110))
        latest = StudioSession(original_vocal=StudioTrackState(volume_percent=140))
        second_song = StudioSession(instrumental=StudioTrackState(muted=True))

        autosave.queue("song-1", first)
        autosave.queue("song-1", latest)
        self.assertEqual(saved, [])

        autosave.queue("song-2", second_song)
        self.assertEqual(saved, [("song-1", latest)])

        autosave.flush()
        self.assertEqual(saved, [("song-1", latest), ("song-2", second_song)])

    def test_reports_save_failure_without_leaving_pending_state(self) -> None:
        def fail(_song_id: str, _session: StudioSession) -> None:
            raise OSError("disk unavailable")

        autosave = StudioSessionAutosave(fail)
        failed = QSignalSpy(autosave.save_failed)
        autosave.queue("song-1", StudioSession())

        autosave.flush()
        autosave.flush()

        self.assertEqual(failed.count(), 1)
        self.assertEqual(failed.at(0)[0], "disk unavailable")


if __name__ == "__main__":
    unittest.main()
