from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_details_panel import LibraryDetailsPanel
from jang_app.services.song_assets import STAGE_SOURCE, STAGE_VOCAL, SongAsset, SongAssetDetails


class LibraryDetailsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_displays_stage_assets_and_emits_navigation_actions(self) -> None:
        panel = LibraryDetailsPanel()
        source = SongAsset(STAGE_SOURCE, "Source", Path("source.wav"), is_active=True, size_bytes=1024)
        vocal = SongAsset(STAGE_VOCAL, "Original Vocal", Path("vocals.wav"), version_label="Run 01")
        details = SongAssetDetails(
            song_id="song-1",
            title="Song One",
            source_type="local",
            source_url="",
            original_name="source.wav",
            package_dir=Path("song-package"),
            created_at="2026-08-02T10:30:00+00:00",
            assets=(source, vocal),
        )
        opened = QSignalSpy(panel.open_location_requested)
        vocal_requested = QSignalSpy(panel.open_vocal_requested)
        back_requested = QSignalSpy(panel.back_requested)

        panel.set_details(details)

        self.assertEqual(panel.song_id, "song-1")
        self.assertEqual(panel.title_label.text(), "Song One")
        self.assertEqual(len(panel.source_page.asset_rows), 1)
        self.assertEqual(len(panel.vocal_page.asset_rows), 1)
        panel.source_page.asset_rows[0].open_button.click()
        panel.open_package_button.click()
        panel.open_vocal_button.click()
        panel.back_button.click()

        self.assertEqual(opened.count(), 2)
        self.assertEqual(opened.at(0)[0], Path("source.wav"))
        self.assertEqual(opened.at(1)[0], Path("song-package"))
        self.assertEqual(vocal_requested.at(0)[0], "song-1")
        self.assertEqual(back_requested.count(), 1)
        panel.close()

    def test_output_recovery_cannot_open_vocal_processing(self) -> None:
        panel = LibraryDetailsPanel()
        panel.set_details(
            SongAssetDetails(
                song_id="output-1",
                title="Recovered Output",
                source_type="output",
                source_url="",
                original_name="",
                package_dir=Path("output-package"),
                created_at="",
                assets=(),
            )
        )

        self.assertFalse(panel.open_vocal_button.isEnabled())
        panel.close()


if __name__ == "__main__":
    unittest.main()
