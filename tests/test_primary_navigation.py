from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.primary_navigation import PrimaryNavigationBar


class PrimaryNavigationBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_data_and_export_pages_are_separate_from_the_connected_workflow(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Vocal", 2), ("Studio", 3)),
            ("Export", 4),
        )
        requested = QSignalSpy(navigation.page_requested)

        navigation.workflow_buttons[1].click()

        self.assertEqual(requested.at(0)[0], 3)
        self.assertEqual(navigation.button_group.checkedId(), 3)
        self.assertTrue(
            all(button.objectName() == "WorkflowNavButton" for button in navigation.workflow_buttons)
        )
        self.assertTrue(
            all(button.objectName() == "StandaloneNavButton" for button in navigation.leading_buttons)
        )
        self.assertEqual(navigation.export_button.objectName(), "ExportNavButton")
        navigation.set_current_page(0)
        self.assertTrue(navigation.leading_buttons[0].isChecked())
        navigation.close()


if __name__ == "__main__":
    unittest.main()
