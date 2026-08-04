from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.video_preview_panel import VideoPlaybackSynchronizer, VideoPreviewPanel
from jang_app.services.video_source import VIDEO_KIND_FILE, VIDEO_KIND_YOUTUBE, VideoSource


class VideoPreviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

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
