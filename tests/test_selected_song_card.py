from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.selected_song_card import SelectedSongCard


class SelectedSongCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_populates_without_signal_and_emits_selected_song_id(self) -> None:
        card = SelectedSongCard()
        changed = QSignalSpy(card.song_changed)

        card.set_songs((("one", "Song One"), ("two", "Song Two")), "one")

        self.assertEqual(card.selected_song_id(), "one")
        self.assertEqual(changed.count(), 0)
        card.select_song("two", emit=True)
        self.assertEqual(card.selected_song_id(), "two")
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0], "two")
        card.close()


if __name__ == "__main__":
    unittest.main()
