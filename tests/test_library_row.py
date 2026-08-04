from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
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

    def test_row_requests_shared_preview_without_embedding_transport(self) -> None:
        row = SongListRow(
            "song-1",
            "A title long enough to require the overflow treatment",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        requested = QSignalSpy(row.preview_requested)
        normal_height = row.sizeHint().height()
        row.resize(720, normal_height)
        row.show()
        self.app.processEvents()

        QTest.mouseClick(row.title_label, Qt.MouseButton.LeftButton)

        self.assertEqual(requested.at(0)[0], "song-1")
        self.assertEqual(row.sizeHint().height(), normal_height)
        self.assertFalse(hasattr(row, "preview_transport"))
        self.assertGreaterEqual(row.waveform.minimumWidth(), 190)
        row.close()


if __name__ == "__main__":
    unittest.main()
