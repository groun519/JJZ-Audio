from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

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

            panel.set_source(VideoSource(kind=VIDEO_KIND_FILE, path=video, original_name="video.mp4"))
            self.assertTrue(panel.has_local_source)
            self.assertIs(panel.stack.currentWidget(), panel.video_widget)

            panel.set_source(VideoSource(kind=VIDEO_KIND_YOUTUBE, url="https://youtu.be/source"))
            self.assertFalse(panel.has_local_source)
            self.assertIs(panel.stack.currentWidget(), panel.empty_widget)
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
