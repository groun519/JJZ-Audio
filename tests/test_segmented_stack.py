from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.segmented_stack import SegmentedStack


class SegmentedStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_switches_any_number_of_sections_with_one_selected_button(self) -> None:
        control = SegmentedStack((("One", QWidget()), ("Two", QWidget()), ("Three", QWidget())))
        changed = QSignalSpy(control.current_changed)

        control.button_group.button(2).click()

        self.assertEqual(control.current_index(), 2)
        self.assertTrue(control.button_group.button(2).isChecked())
        self.assertFalse(control.button_group.button(0).isChecked())
        self.assertEqual(changed.count(), 1)
        control.close()


if __name__ == "__main__":
    unittest.main()
