from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.video_preview_panel import VideoPlaybackSynchronizer, VideoPreviewPanel
from jang_app.qt_app.widgets import DangerIconButton
from jang_app.services.video_source import VIDEO_KIND_FILE, VIDEO_KIND_YOUTUBE, VideoSource


class VideoPreviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_compact_mode_fits_above_studio_timeline(self) -> None:
        panel = VideoPreviewPanel()

        panel.set_compact_mode(True)

        self.assertGreater(panel.maximumHeight(), 250)
        self.assertLessEqual(panel.minimumHeight(), 190)
        self.assertGreater(panel.drop_card.maximumHeight(), 250)
        self.assertGreaterEqual(panel.drop_card.minimumHeight(), 96)

    def test_sync_corrects_drift_and_mirrors_playback_state(self) -> None:
        player = _FakePlayer(position=900)
        synchronizer = VideoPlaybackSynchronizer(player, drift_limit_ms=180)

        synchronizer.sync(1000, True)
        self.assertEqual(player.seeks, [])
        self.assertEqual(player.play_count, 1)

        synchronizer.sync(1400, True)
        self.assertEqual(player.seeks, [1400])

        synchronizer.sync(1400, False)
        self.assertEqual(player.pause_count, 1)

    def test_switches_between_local_preview_and_url_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "video.mp4"
            video.write_bytes(b"video")
            panel = VideoPreviewPanel()

            panel.set_source(
                VideoSource(kind=VIDEO_KIND_FILE, path=video, original_name="video.mp4"),
                enabled=True,
            )
            self.assertTrue(panel.has_local_source)
            self.assertIs(panel.stack.currentWidget(), panel.video_widget)

            panel.set_source(
                VideoSource(kind=VIDEO_KIND_YOUTUBE, url="https://youtu.be/source"),
                enabled=True,
            )
            self.assertFalse(panel.has_local_source)
            self.assertIs(panel.stack.currentWidget(), panel.source_editor)
            panel.close()

    def test_local_image_uses_the_static_media_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "cover.png"
            image.write_bytes(b"image")
            panel = VideoPreviewPanel()

            panel.set_source(
                VideoSource(kind=VIDEO_KIND_FILE, path=image, original_name="cover.png"),
                enabled=True,
            )

            self.assertEqual(panel._source.media_kind, "image")
            self.assertIs(panel.stack.currentWidget(), panel.image_widget)
            panel.close()

    def test_timeline_media_switches_between_image_and_empty_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "cover.png"
            image.write_bytes(b"image")
            panel = VideoPreviewPanel()
            panel.set_source(VideoSource(), enabled=True)
            panel.set_active(True)

            panel.sync_timeline_media(image, "image", 0, True)
            self.assertIs(panel.stack.currentWidget(), panel.image_widget)
            self.assertEqual(panel._preview_path, image.resolve())

            panel.sync_timeline_media(None, "", 0, False)
            self.assertIs(panel.stack.currentWidget(), panel.image_widget)
            self.assertIsNone(panel._preview_path)
            panel.close()

    def test_original_youtube_url_action_attaches_the_work_song_source(self) -> None:
        panel = VideoPreviewPanel()
        requested = QSignalSpy(panel.url_requested)
        source_url = "https://youtube.com/watch?v=source"

        panel.set_source(VideoSource(), enabled=True, original_song_url=source_url)
        panel.url_field.original_button.show()
        panel.url_field.original_button.click()

        self.assertEqual(panel.url_field.edit.text(), source_url)
        self.assertEqual(requested.at(0)[0], source_url)
        panel.close()

    def test_original_url_slot_is_transparent_while_hover_action_is_hidden(self) -> None:
        panel = VideoPreviewPanel()
        panel.setStyleSheet(build_stylesheet("dark"))
        panel.set_source(
            VideoSource(),
            enabled=True,
            original_song_url="https://youtube.com/watch?v=source",
        )

        self.assertEqual(panel.url_field.original_slot.objectName(), "VideoOriginalUrlSlot")
        self.assertEqual(panel.url_field.original_button.objectName(), "VideoOriginalUrlButton")
        self.assertEqual(panel.url_field.original_button.icon_name(), "youtube")
        self.assertEqual(
            (panel.url_field.original_slot.width(), panel.url_field.original_slot.height()),
            (30, 30),
        )
        self.assertEqual(
            (panel.url_field.original_button.width(), panel.url_field.original_button.height()),
            (30, 30),
        )
        self.assertFalse(panel.url_field.original_slot.isHidden())
        self.assertTrue(panel.url_field.original_button.isHidden())
        self.assertIn(
            "QWidget#VideoOriginalUrlSlot",
            panel.styleSheet(),
        )
        panel.close()

    def test_url_action_is_explicit_and_only_enabled_for_non_empty_input(self) -> None:
        for theme_mode in ("dark", "white"):
            panel = VideoPreviewPanel()
            panel.setStyleSheet(build_stylesheet(theme_mode))
            panel.set_theme_mode(theme_mode)
            panel.set_source(VideoSource(), enabled=True)
            requested = QSignalSpy(panel.url_requested)

            with self.subTest(theme_mode=theme_mode):
                self.assertEqual(panel.url_field.submit_button.icon_name(), "link")
                self.assertFalse(panel.url_field.submit_button.isEnabled())
                self.assertTrue(panel.url_field.original_slot.isHidden())

                panel.url_field.edit.setText("https://example.com/video.mp4")
                self.assertTrue(panel.url_field.submit_button.isEnabled())
                panel.url_field.submit_button.click()
                self.assertEqual(requested.count(), 1)
            panel.close()

    def test_youtube_download_uses_a_compact_icon_action(self) -> None:
        for theme_mode in ("dark", "white"):
            panel = VideoPreviewPanel()
            panel.setStyleSheet(build_stylesheet(theme_mode))
            requested = QSignalSpy(panel.download_requested)
            panel.set_source(
                VideoSource(kind=VIDEO_KIND_YOUTUBE, url="https://youtu.be/source"),
                enabled=True,
            )
            panel.resize(720, 520)
            panel.show()
            self.app.processEvents()

            with self.subTest(theme_mode=theme_mode):
                self.assertEqual(panel.download_button.icon_name(), "download")
                self.assertIsInstance(panel.clear_button, DangerIconButton)
                self.assertEqual(
                    {
                        (button.width(), button.height())
                        for button in (panel.download_button, panel.open_button, panel.clear_button)
                    },
                    {(30, 30)},
                )
                self.assertFalse(panel.download_button.isHidden())
                panel.download_button.click()
                self.assertEqual(requested.count(), 1)
            panel.close()

    def test_saved_video_selector_reuses_a_managed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "saved.mp4"
            video.write_bytes(b"video")
            panel = VideoPreviewPanel()
            requested = QSignalSpy(panel.saved_source_requested)

            panel.set_source(
                VideoSource(kind=VIDEO_KIND_YOUTUBE, url="https://youtu.be/source"),
                enabled=True,
                saved_sources=(
                    VideoSource(kind=VIDEO_KIND_FILE, path=video, original_name="saved.mp4"),
                ),
            )

            self.assertFalse(panel.saved_source_combo.isHidden())
            self.assertEqual(panel.saved_source_combo.count(), 2)
            panel.saved_source_combo.activated.emit(1)
            self.assertEqual(requested.at(0)[0], video.resolve())
            panel.close()


class _FakePlayer:
    def __init__(self, position: int) -> None:
        self._position = position
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self.seeks: list[int] = []
        self.play_count = 0
        self.pause_count = 0

    def position(self) -> int:
        return self._position

    def setPosition(self, position: int) -> None:  # noqa: N802
        self._position = position
        self.seeks.append(position)

    def playbackState(self):  # noqa: N802
        return self._state

    def play(self) -> None:
        self._state = QMediaPlayer.PlaybackState.PlayingState
        self.play_count += 1

    def pause(self) -> None:
        self._state = QMediaPlayer.PlaybackState.PausedState
        self.pause_count += 1


if __name__ == "__main__":
    unittest.main()
