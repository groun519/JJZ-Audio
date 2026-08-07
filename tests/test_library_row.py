from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_row import SongListRow
from jang_app.qt_app.transport_controls import TRANSPORT_BUTTON_SIZE
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

    def test_row_expands_inline_transport_without_resizing_the_title_column(self) -> None:
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
        row.set_preview_expanded(True)

        self.assertEqual(requested.at(0)[0], "song-1")
        self.assertGreater(row.sizeHint().height(), normal_height)
        self.assertFalse(row.preview_transport.isHidden())
        self.assertGreaterEqual(row.waveform.minimumWidth(), 190)
        self.assertEqual(row.preview_transport.play_button.width(), TRANSPORT_BUTTON_SIZE)
        self.assertEqual(row.preview_transport.play_button.height(), TRANSPORT_BUTTON_SIZE)
        row.close()

    def test_inline_transport_forwards_playback_actions_for_its_song(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        play_requested = QSignalSpy(row.preview_play_toggled)
        seek_requested = QSignalSpy(row.preview_seek_requested)
        row.set_preview_queue(60_000)

        row.preview_transport.play_button.click()
        row.preview_transport.seek_requested.emit(15_000)

        self.assertEqual(play_requested.at(0)[0], "song-1")
        self.assertEqual(seek_requested.at(0), ["song-1", 15_000])
        row.close()


if __name__ == "__main__":
    unittest.main()
