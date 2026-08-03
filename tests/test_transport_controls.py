from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.transport_controls import TransportControls


class TransportControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_seek_signal_uses_duration(self) -> None:
        controls = TransportControls()
        requested = QSignalSpy(controls.seek_requested)
        controls.set_duration(80_000)

        controls.slider.sliderMoved.emit(250)

        self.assertEqual(requested.at(0)[0], 20_000)
        controls.close()

    def test_play_state_uses_square_icon_button(self) -> None:
        controls = TransportControls(button_size=30)

        controls.set_duration(1_000)
        controls.set_playing(True)

        self.assertEqual(controls.play_button.width(), 30)
        self.assertEqual(controls.play_button.height(), 30)
        self.assertEqual(controls.play_button.icon_name(), "stop")
        controls.close()


if __name__ == "__main__":
    unittest.main()
