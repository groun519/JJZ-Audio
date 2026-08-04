from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.floating_playback_panel import (
    FLOATING_PLAYER_HEIGHT,
    FLOATING_PLAYER_WIDTH,
    FloatingPlaybackPanel,
)
from jang_app.qt_app.transport_controls import TRANSPORT_BUTTON_SIZE


class FloatingPlaybackPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_reuses_transport_and_exposes_full_title(self) -> None:
        panel = FloatingPlaybackPanel()
        title = "A long library title that remains available through the tooltip"

        panel.set_queue(title, 90_000)
        panel.set_position(15_000, 90_000)
        panel.set_playing(True)

        self.assertEqual(panel.size().width(), FLOATING_PLAYER_WIDTH)
        self.assertEqual(panel.size().height(), FLOATING_PLAYER_HEIGHT)
        self.assertEqual(panel.title_label.text(), title)
        self.assertEqual(panel.title_label.toolTip(), title)
        self.assertEqual(panel.transport.time_label.text(), "00:15 / 01:30")
        self.assertEqual(panel.transport.play_button.icon_name(), "stop")
        self.assertEqual(panel.transport.play_button.width(), TRANSPORT_BUTTON_SIZE)
        self.assertEqual(panel.transport.play_button.height(), TRANSPORT_BUTTON_SIZE)
        panel.close()

    def test_panel_forwards_transport_and_dismiss_actions(self) -> None:
        panel = FloatingPlaybackPanel()
        play_toggled = QSignalSpy(panel.play_toggled)
        dismiss_requested = QSignalSpy(panel.dismiss_requested)

        panel.set_queue("Song", 1_000)
        panel.transport.play_button.click()
        panel.close_button.click()

        self.assertEqual(play_toggled.count(), 1)
        self.assertEqual(dismiss_requested.count(), 1)
        panel.close()


if __name__ == "__main__":
    unittest.main()
