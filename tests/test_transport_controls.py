from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.transport_controls import TRANSPORT_BUTTON_SIZE, TransportControls


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
        for theme_mode in ("dark", "white"):
            controls = TransportControls()
            controls.setStyleSheet(build_stylesheet(theme_mode))
            controls.set_duration(1_000)
            controls.set_playing(True)
            controls.ensurePolished()

            with self.subTest(theme_mode=theme_mode):
                self.assertEqual(controls.play_button.width(), TRANSPORT_BUTTON_SIZE)
                self.assertEqual(controls.play_button.height(), TRANSPORT_BUTTON_SIZE)
                self.assertEqual(controls.play_button.icon_name(), "stop")

            controls.close()


if __name__ == "__main__":
    unittest.main()
