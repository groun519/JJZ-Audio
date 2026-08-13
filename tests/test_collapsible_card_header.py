from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.collapsible_card_header import CollapsibleCardHeader


class CollapsibleCardHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_toggle_updates_state_icon_and_signal(self) -> None:
        header = CollapsibleCardHeader("Model Settings")
        states: list[bool] = []
        header.toggled.connect(states.append)

        header.toggle_button.click()

        self.assertTrue(header.is_expanded())
        self.assertEqual(header.toggle_button.icon_name(), "chevron_up")
        self.assertEqual(states, [True])

        header.toggle_button.click()

        self.assertFalse(header.is_expanded())
        self.assertEqual(header.toggle_button.icon_name(), "chevron_down")
        self.assertEqual(states, [True, False])


if __name__ == "__main__":
    unittest.main()
