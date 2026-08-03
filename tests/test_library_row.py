from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_row import SongListRow
from jang_app.services.song_metadata import SongDisplayMetadata


class SongListRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_song_details_is_the_second_hover_action(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        requested = QSignalSpy(row.details_requested)

        self.assertEqual(
            row.action_buttons,
            (row.use_button, row.details_button, row.rename_button, row.remove_button),
        )
        row.details_button.click()

        self.assertEqual(requested.at(0)[0], "song-1")
        row.close()


if __name__ == "__main__":
    unittest.main()
