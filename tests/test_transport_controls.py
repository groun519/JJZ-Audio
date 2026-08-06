from __future__ import annotations

import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
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

    def test_track_click_requests_seek_at_clicked_position(self) -> None:
        controls = TransportControls()
        controls.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        controls.resize(800, 50)
        controls.set_duration(80_000)
        controls.show()
        self.app.processEvents()
        requested = QSignalSpy(controls.seek_requested)
        target = QPoint(round(controls.slider.width() * 0.75), controls.slider.height() // 2)

        QTest.mouseClick(controls.slider, Qt.MouseButton.LeftButton, pos=target)

        self.assertGreaterEqual(requested.count(), 1)
        self.assertGreater(requested.at(requested.count() - 1)[0], 50_000)
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
