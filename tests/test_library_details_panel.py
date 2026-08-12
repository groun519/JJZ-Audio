from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_details_panel import LibraryDetailsPanel
from jang_app.services.i18n import tr
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
        back_requested = QSignalSpy(panel.back_requested)

        panel.set_details(details)

        self.assertEqual(panel.song_id, "song-1")
        self.assertEqual(panel.title_label.text(), "Song One")
        self.assertEqual(len(panel.source_page.asset_rows), 1)
        self.assertEqual(len(panel.vocal_page.asset_rows), 1)
        panel.source_page.asset_rows[0].open_button.click()
        panel.open_package_button.click()
        panel.back_button.click()

        self.assertEqual(opened.count(), 2)
        self.assertEqual(opened.at(0)[0], Path("source.wav"))
        self.assertEqual(opened.at(1)[0], Path("song-package"))
        self.assertEqual(back_requested.count(), 1)
        self.assertFalse(hasattr(panel, "open_vocal_button"))
        self.assertFalse(hasattr(panel, "open_vocal_requested"))
        protected_row = panel.source_page.asset_rows[0]
        self.assertTrue(protected_row.remove_button.isHidden())
        protected_row._set_remove_emphasis(True)
        self.assertFalse(protected_row.remove_button.isHidden())
        self.assertFalse(protected_row.remove_button.isEnabled())
        self.assertEqual(
            protected_row.remove_button.toolTip(),
            tr("This file can only be removed by deleting the entire song."),
        )
        protected_row._set_remove_emphasis(False)
        panel.close()

    def test_emits_remove_request_for_removable_asset(self) -> None:
        panel = LibraryDetailsPanel()
        exported = SongAsset(
            "export",
            "Exported Asset",
            Path("mix.wav"),
            removal_scope="file",
        )
        panel.set_details(
            SongAssetDetails(
                song_id="song-1",
                title="Song One",
                source_type="local",
                source_url="",
                original_name="source.wav",
                package_dir=Path("song-package"),
                created_at="",
                assets=(exported,),
            )
        )
        removed = QSignalSpy(panel.remove_asset_requested)
        row = panel.export_page.asset_rows[0]

        self.assertTrue(row.remove_button.isHidden())
        self.assertEqual(row.remove_slot.width(), 30)
        self.assertTrue(row.remove_button.property("persistentDanger"))
        row._set_remove_emphasis(True)
        self.assertTrue(row.remove_button.property("contextHover"))
        self.assertFalse(row.remove_button.isHidden())
        row.remove_button.click()
        row._set_remove_emphasis(False)

        self.assertEqual(removed.count(), 1)
        self.assertEqual(removed.at(0)[0], "song-1")
        self.assertEqual(removed.at(0)[1], exported)
        self.assertFalse(row.remove_button.property("contextHover"))
        self.assertTrue(row.remove_button.isHidden())
        self.assertEqual(row.remove_slot.width(), 30)
        self.assertEqual(row.remove_button.height(), 30)
        self.assertEqual(
            (row.open_button.width(), row.open_button.height()),
            (30, 30),
        )
        panel.close()

    def test_selection_mode_checks_removable_rows_and_emits_one_bulk_request(self) -> None:
        panel = LibraryDetailsPanel()
        first = SongAsset(
            "export",
            "Exported Asset",
            Path("first.wav"),
            removal_scope="file",
        )
        second = SongAsset(
            "export",
            "Exported Asset",
            Path("second.wav"),
            removal_scope="file",
        )
        protected = SongAsset("export", "Exported Asset", Path("source.wav"))
        panel.set_details(
            SongAssetDetails(
                song_id="song-1",
                title="Song One",
                source_type="local",
                source_url="",
                original_name="source.wav",
                package_dir=Path("song-package"),
                created_at="",
                assets=(first, second, protected),
            )
        )
        requested = QSignalSpy(panel.remove_assets_requested)
        page = panel.export_page
        first_row, second_row, protected_row = page.asset_rows

        page.selection_mode_button.click()

        self.assertFalse(first_row.selection_checkbox.isHidden())
        self.assertFalse(second_row.selection_checkbox.isHidden())
        self.assertFalse(protected_row.selection_checkbox.isEnabled())
        first_row.selection_checkbox.click()
        QTest.mouseClick(second_row, Qt.MouseButton.LeftButton)

        self.assertEqual(page.selected_count_label.text(), tr("{count} selected", count=2))
        self.assertTrue(page.bulk_remove_button.isEnabled())
        page.bulk_remove_button.click()

        self.assertEqual(requested.count(), 1)
        self.assertEqual(requested.at(0)[0], "song-1")
        self.assertEqual(requested.at(0)[1], (first, second))
        panel.close()

    def test_audio_asset_rows_expand_into_a_single_inline_preview(self) -> None:
        panel = LibraryDetailsPanel()
        vocal = SongAsset(STAGE_VOCAL, "Original Vocal", Path("vocals.wav"))
        exported = SongAsset("export", "Exported Asset", Path("mix.wav"))
        video = SongAsset("export", "Exported Asset", Path("cover.mp4"))
        panel.set_details(
            SongAssetDetails(
                song_id="song-1",
                title="Song One",
                source_type="local",
                source_url="",
                original_name="source.wav",
                package_dir=Path("song-package"),
                created_at="",
                assets=(vocal, exported, video),
            )
        )
        requested = QSignalSpy(panel.preview_requested)
        played = QSignalSpy(panel.preview_play_toggled)
        sought = QSignalSpy(panel.preview_seek_requested)
        vocal_row = panel.vocal_page.asset_rows[0]
        export_row = panel.export_page.asset_rows[0]
        video_row = panel.export_page.asset_rows[1]

        QTest.mouseClick(vocal_row, Qt.MouseButton.LeftButton)
        self.assertEqual(requested.at(0)[0], Path("vocals.wav"))

        panel.set_preview_expanded(vocal.path, True)
        self.assertFalse(vocal_row.preview_transport.isHidden())
        panel.set_preview_queue(vocal.path, 10_000)
        vocal_row.preview_transport.play_button.click()
        vocal_row.preview_transport.slider.sliderMoved.emit(500)

        self.assertEqual(played.at(0)[0], Path("vocals.wav"))
        self.assertEqual(sought.at(0)[0], Path("vocals.wav"))
        self.assertEqual(sought.at(0)[1], 5_000)

        panel.set_preview_expanded(exported.path, True)
        self.assertTrue(vocal_row.preview_transport.isHidden())
        self.assertFalse(export_row.preview_transport.isHidden())
        QTest.mouseClick(video_row, Qt.MouseButton.LeftButton)
        self.assertEqual(requested.count(), 1)
        self.assertTrue(video_row.preview_transport.isHidden())
        panel.close()

    def test_long_asset_names_keep_row_actions_inside_the_viewport(self) -> None:
        panel = LibraryDetailsPanel()
        panel.resize(900, 600)
        asset = SongAsset(
            "vocal",
            "Converted Vocal",
            Path(f"{'converted_vocal_' * 20}.wav"),
            removal_scope="vocal_take",
        )
        panel.set_details(
            SongAssetDetails(
                song_id="song-1",
                title="A very long song title " * 20,
                source_type="local",
                source_url="",
                original_name="source.wav",
                package_dir=Path("song-package"),
                created_at="",
                assets=(asset,),
            )
        )
        panel.stage_stack.set_current_index(1)
        panel.show()
        self.app.processEvents()
        row = panel.vocal_page.asset_rows[0]

        self.assertLessEqual(row.width(), panel.vocal_page.asset_scroll.viewport().width())
        self.assertLessEqual(row.action_container.geometry().right(), row.contentsRect().right())
        self.assertLess(row.remove_button.geometry().x(), row.open_button.geometry().x())
        self.assertFalse(row.remove_button.isVisible())
        row._set_remove_emphasis(True)
        self.assertTrue(row.remove_button.isVisible())
        panel.close()

    def test_output_recovery_uses_the_same_compact_header(self) -> None:
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

        self.assertFalse(hasattr(panel, "open_vocal_button"))
        self.assertTrue(panel.open_package_button.isEnabled())
        panel.close()


if __name__ == "__main__":
    unittest.main()
