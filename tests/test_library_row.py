from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_row import SongListRow
from jang_app.qt_app.transport_controls import TRANSPORT_BUTTON_SIZE
from jang_app.qt_app.widgets import COMPACT_ICON_BUTTON_SIZE, DangerIconButton
from jang_app.services.song_metadata import SongDisplayMetadata


class SongListRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_song_details_is_the_first_trailing_hover_action(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        requested = QSignalSpy(row.details_requested)

        self.assertEqual(
            row.action_buttons,
            (
                row.details_button,
                row.rename_button,
                row.remove_button,
            ),
        )
        self.assertIsInstance(row.remove_button, DangerIconButton)
        self.assertTrue(row.remove_button.property("persistentDanger"))
        self.assertTrue(
            all(
                button.size().toTuple()
                == (COMPACT_ICON_BUTTON_SIZE, COMPACT_ICON_BUTTON_SIZE)
                for button in row.action_buttons
            )
        )
        row.details_button.click()

        self.assertEqual(requested.at(0)[0], "song-1")
        row.close()

    def test_work_song_action_reveals_before_content_and_persists_when_active(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        requested = QSignalSpy(row.work_song_toggled)
        self.assertTrue(row.work_song_reveal.isHidden())
        self.assertEqual(row.work_song_reveal.maximumWidth(), 0)

        row.resize(960, row.sizeHint().height())
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.show()
        self.app.processEvents()
        row.work_song_reveal._animation.setDuration(0)
        row._is_hovered = False
        row._sync_action_visibility()
        self.app.processEvents()
        initial_badge_x = row.source_badge.mapTo(row, row.source_badge.rect().topLeft()).x()
        initial_waveform_geometry = row.waveform.geometry()

        self.assertFalse(row.work_song_button.isVisible())

        row._is_hovered = True
        row._sync_action_visibility()
        self.app.processEvents()

        revealed_badge_x = row.source_badge.mapTo(row, row.source_badge.rect().topLeft()).x()
        self.assertTrue(row.work_song_button.isVisible())
        self.assertEqual(
            row.work_song_reveal.maximumWidth(),
            row.work_song_reveal.expanded_width(),
        )
        self.assertGreater(revealed_badge_x, initial_badge_x + 25)
        self.assertLess(
            row.work_song_button.mapTo(row, row.work_song_button.rect().topLeft()).x(),
            revealed_badge_x,
        )
        self.assertEqual(row.waveform.geometry(), initial_waveform_geometry)

        row.set_work_song_active(True)
        self.app.processEvents()
        self.assertTrue(row.work_song_button.isChecked())
        self.assertTrue(row.work_song_button.isVisible())
        self.assertTrue(row.property("workSong"))
        self.assertEqual(row.waveform.geometry(), initial_waveform_geometry)

        row._is_hovered = False
        row._sync_action_visibility()
        self.assertFalse(row.work_song_button.isHidden())

        row.work_song_button.click()
        self.assertEqual(requested.at(0)[0], "song-1")

        row.set_work_song_active(False)
        self.assertFalse(row.work_song_button.isChecked())
        self.assertFalse(row.work_song_button.isVisible())
        self.assertEqual(row.work_song_reveal.maximumWidth(), 0)
        self.assertFalse(row.property("workSong"))
        row.close()

    def test_unchanged_work_song_state_does_not_repolish_the_row(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )

        with patch.object(row, "_refresh_style") as refresh_style:
            row.set_work_song_active(False)
            refresh_style.assert_not_called()
            row.set_work_song_active(True)
            refresh_style.assert_called_once()

        row.close()

    def test_work_song_loading_keeps_action_visible_and_animates_border(self) -> None:
        row = SongListRow(
            "song-1",
            "Song",
            SongDisplayMetadata("local", "LOCAL", "WAV", "01:00", "1.0 MB", None),
        )
        row.resize(960, row.sizeHint().height())
        row.show()
        self.app.processEvents()
        initial_phase = row.work_song_button._loading_phase

        row.set_work_song_loading(True)
        QTest.qWait(60)

        self.assertTrue(row.work_song_button.is_loading())
        self.assertTrue(row.work_song_button.isVisible())
        self.assertFalse(row.work_song_button.isEnabled())
        self.assertNotEqual(row.work_song_button._loading_phase, initial_phase)

        row._is_hovered = False
        completed = QSignalSpy(row.work_song_button.loading_finished)
        row.set_work_song_loading(False)
        self.assertTrue(row.work_song_button.is_loading())
        QTest.qWait(650)
        self.assertFalse(row.work_song_button.is_loading())
        self.assertTrue(row.work_song_button.isEnabled())
        self.assertFalse(row.work_song_button.isVisible())
        self.assertEqual(completed.count(), 1)
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
