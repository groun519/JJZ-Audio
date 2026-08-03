from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.export_page import ExportPage
from jang_app.services.song_export import SongAudioExport
from jang_app.services.song_video_export import SongVideoExport


class ExportPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_target_song_is_emitted_by_independent_export_actions(self) -> None:
        page = ExportPage()
        page.set_songs((("song-1", "Song One"),), "song-1")
        page.set_target_song("song-1", audio_enabled=True, video_enabled=True)
        audio_requested = QSignalSpy(page.audio_export_requested)
        video_requested = QSignalSpy(page.video_export_requested)

        page.audio_action.button.click()
        page.video_action.button.click()

        self.assertEqual(audio_requested.at(0)[0], "song-1")
        self.assertEqual(video_requested.at(0)[0], "song-1")
        page.close()

    def test_audio_and_video_rows_share_the_managed_export_location(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports"
        audio = SongAudioExport(export_dir / "audio" / "mix.wav", 2048, 1_786_000_000)
        video = SongVideoExport(export_dir / "video" / "video.mp4", 4096, 1_786_000_100)
        opened = QSignalSpy(page.open_location_requested)

        page.set_exports((audio,), (video,), export_dir)
        page.export_rows[0].open_button.click()
        page.open_folder_button.click()

        self.assertEqual(len(page.export_rows), 2)
        self.assertEqual(opened.at(0)[0], video.path)
        self.assertEqual(opened.at(1)[0], export_dir)
        page.close()

    def test_changing_target_song_resets_both_actions_without_unlocking_running_task(self) -> None:
        page = ExportPage()
        page.set_songs((("song-1", "Song One"), ("song-2", "Song Two")), "song-1")
        page.set_target_song("song-1", audio_enabled=True, video_enabled=True)
        page.set_audio_progress(64)
        page.set_audio_status("Exporting audio mix")
        page.set_audio_running(True)

        page.set_target_song("song-2", audio_enabled=True, video_enabled=False)

        self.assertEqual(page.audio_action.progress_bar.value(), 0)
        self.assertTrue(page.audio_action.status_label.isHidden())
        self.assertFalse(page.audio_action.button.isEnabled())
        self.assertFalse(page.video_action.button.isEnabled())
        page.set_audio_running(False)
        self.assertTrue(page.audio_action.button.isEnabled())
        page.close()

    def test_selector_changes_only_the_export_target(self) -> None:
        page = ExportPage()
        page.set_songs((("song-1", "Song One"), ("song-2", "Song Two")), "song-1")
        changed = QSignalSpy(page.song_changed)

        page.song_selector.activated.emit(2)

        self.assertEqual(changed.at(0)[0], "song-2")
        self.assertEqual(page.selected_song_id(), "song-2")
        page.close()


if __name__ == "__main__":
    unittest.main()
