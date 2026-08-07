from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.export_page import ExportPage
from jang_app.services.google_drive_share import drive_share_target_id
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

    def test_export_row_emits_drive_share_request(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports"
        audio = SongAudioExport(export_dir / "audio" / "mix.wav", 2048, 1_786_000_000)
        shared = QSignalSpy(page.share_requested)
        page.set_exports((audio,), (), export_dir)

        page.export_rows[0].share_button.click()

        self.assertEqual(shared.at(0)[0], audio.path)
        self.assertTrue(page.export_rows[0].share_action.progress_bar.isHidden())
        page.close()

    def test_drive_share_actions_follow_feature_availability(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports"
        audio = SongAudioExport(export_dir / "audio" / "mix.wav", 2048, 1_786_000_000)
        page.set_exports((audio,), (), export_dir)

        page.set_sharing_enabled(False)

        self.assertTrue(page.export_rows[0].share_button.isHidden())
        self.assertFalse(page.export_rows[0].share_button.isEnabled())
        page.set_sharing_enabled(True)
        self.assertFalse(page.export_rows[0].share_button.isHidden())
        self.assertTrue(page.export_rows[0].share_button.isEnabled())
        page.close()

    def test_export_row_displays_drive_upload_progress_inline(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports"
        audio = SongAudioExport(export_dir / "audio" / "mix.wav", 2048, 1_786_000_000)
        page.set_exports((audio,), (), export_dir)
        row = page.export_rows[0]
        target_id = drive_share_target_id(audio.path)

        page.set_share_started(target_id)
        page.set_share_progress(target_id, 63)

        self.assertFalse(row.share_action.progress_bar.isHidden())
        self.assertEqual(row.share_action.progress_bar.value(), 63)
        self.assertEqual(row.share_action.progress_label.text(), "63%")
        self.assertTrue(row.share_button.isHidden())

        page.set_share_failed(target_id)
        self.assertTrue(row.share_action.progress_bar.isHidden())
        self.assertFalse(row.share_button.isHidden())
        page.close()

    def test_shared_export_is_marked_and_can_request_drive_deletion(self) -> None:
        page = ExportPage()
        export_dir = Path("song-package") / "04_exports"
        audio = SongAudioExport(export_dir / "audio" / "mix.wav", 2048, 1_786_000_000)
        deleted = QSignalSpy(page.delete_share_requested)
        page.set_exports((audio,), (), export_dir)

        page.set_share_status_provider(lambda _path: True)
        row = page.export_rows[0]
        row.share_action.set_actions_expanded(True)

        self.assertEqual(row.share_button.icon_name(), "cloud_check")
        self.assertFalse(row.share_action.delete_button.isHidden())
        row.share_action.delete_button.click()
        self.assertEqual(deleted.at(0)[0], audio.path)

        page.set_share_deleted(row.target_id)
        self.assertEqual(row.share_button.icon_name(), "link")
        page.close()


if __name__ == "__main__":
    unittest.main()
