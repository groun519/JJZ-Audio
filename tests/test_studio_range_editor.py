from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_range_editor import StudioRangeEditor, TimelineRangeSlider


class StudioRangeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_range_is_clamped_and_full_range_uses_compact_session_values(self) -> None:
        editor = StudioRangeEditor()
        editor.set_timeline(120_000, 10_000, 90_000)

        self.assertEqual(editor.range_values(), (10_000, 90_000))
        self.assertEqual(editor.session_values(), (10_000, 90_000))

        changed = QSignalSpy(editor.range_changed)
        editor.reset_button.click()

        self.assertEqual(editor.range_values(), (0, 120_000))
        self.assertEqual(editor.session_values(), (0, 0))
        self.assertEqual(changed.at(0), [0, 120_000])
        editor.close()

    def test_slider_keeps_a_nonempty_range(self) -> None:
        slider = TimelineRangeSlider()
        slider.set_range(10_000, 9_999, 10_000)
        self.assertEqual(slider.end_ms, 10_000)
        self.assertLess(slider.start_ms, slider.end_ms)

        slider.set_values(-200, 50_000, emit=False)
        self.assertEqual((slider.start_ms, slider.end_ms), (0, 10_000))
        slider.close()


if __name__ == "__main__":
    unittest.main()
