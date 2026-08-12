from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.result_transport_bar import ResultTransportBar
from jang_app.qt_app.theme import build_stylesheet


class ResultTransportBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_is_compact_and_emits_shared_playback_actions(self) -> None:
        bar = ResultTransportBar()
        played = QSignalSpy(bar.play_toggled)
        bar.set_queue(60_000)
        bar.resize(900, bar.height())
        bar.show()
        self.app.processEvents()

        bar.transport.play_button.click()

        self.assertEqual(bar.height(), 54)
        self.assertEqual(played.count(), 1)
        self.assertEqual(bar.transport.time_label.text(), "00:00 / 01:00")
        bar.close()

    def test_play_button_fits_both_themes(self) -> None:
        for theme_mode in ("dark", "white"):
            bar = ResultTransportBar()
            bar.setStyleSheet(build_stylesheet(theme_mode))
            bar.resize(900, bar.height())
            bar.show()
            self.app.processEvents()

            with self.subTest(theme_mode=theme_mode):
                self.assertLessEqual(
                    bar.transport.play_button.geometry().bottom(),
                    bar.transport.contentsRect().bottom(),
                )
                self.assertIn("Space", bar.transport.play_button.toolTip())
            bar.close()


if __name__ == "__main__":
    unittest.main()
