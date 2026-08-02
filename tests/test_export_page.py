from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.export_page import ExportPage
from jang_app.services.song_export import SongAudioExport


class ExportPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selected_song_is_emitted_by_export_action(self) -> None:
        page = ExportPage()
        page.song_card.set_songs((("song-1", "Song One"),), "song-1")
        page.set_export_enabled(True)
        requested = QSignalSpy(page.export_requested)

        page.action.button.click()

        self.assertEqual(requested.count(), 1)
        self.assertEqual(requested.at(0)[0], "song-1")
        page.close()

    def test_export_rows_and_folder_actions_use_managed_paths(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports" / "audio"
        exported = SongAudioExport(export_dir / "mix.wav", 2048, 1_786_000_000)
        opened = QSignalSpy(page.open_location_requested)

        page.set_exports((exported,), export_dir)
        page.export_rows[0].open_button.click()
        page.open_folder_button.click()

        self.assertEqual(len(page.export_rows), 1)
        self.assertEqual(opened.at(0)[0], exported.path)
        self.assertEqual(opened.at(1)[0], export_dir)
        page.close()


if __name__ == "__main__":
    unittest.main()
