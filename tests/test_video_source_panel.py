from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.video_source_panel import VideoSourcePanel
from jang_app.services.video_source import VIDEO_KIND_FILE, VIDEO_KIND_YOUTUBE, VideoSource


class VideoSourcePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_displays_file_source_and_emits_url(self) -> None:
        panel = VideoSourcePanel()
        source = VideoSource(kind=VIDEO_KIND_FILE, path=Path("managed.mp4"), original_name="Original.mp4")
        requested = QSignalSpy(panel.url_requested)

        panel.set_source(source, enabled=True)
        panel.url_edit.setText("https://example.test/video")
        panel.url_button.click()

        self.assertEqual(panel.source_name.text(), "Original.mp4")
        self.assertFalse(panel.open_button.isHidden())
        self.assertEqual(requested.at(0)[0], "https://example.test/video")
        panel.close()

    def test_inherited_source_cannot_be_cleared_and_running_locks_inputs(self) -> None:
        panel = VideoSourcePanel()
        source = VideoSource(
            kind=VIDEO_KIND_YOUTUBE,
            url="https://youtube.com/watch?v=source",
            original_name="Song",
            inherited=True,
        )

        panel.set_source(source, enabled=True)
        panel.set_running(True)

        self.assertTrue(panel.clear_button.isHidden())
        self.assertFalse(panel.url_button.isEnabled())
        self.assertFalse(panel.drop_card.isEnabled())
        panel.set_running(False)
        self.assertTrue(panel.url_button.isEnabled())
        self.assertFalse(panel.download_button.isHidden())
        download_requested = QSignalSpy(panel.download_requested)
        panel.download_button.click()
        self.assertEqual(download_requested.count(), 1)
        panel.close()


if __name__ == "__main__":
    unittest.main()
