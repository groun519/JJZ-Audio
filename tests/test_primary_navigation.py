from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.primary_navigation import PrimaryNavigationBar


class PrimaryNavigationBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_library_is_separate_from_the_connected_workflow_pages(self) -> None:
        navigation = PrimaryNavigationBar(
            ("Library", 0),
            (("Vocal", 1), ("Studio", 2), ("Export", 3)),
        )
        requested = QSignalSpy(navigation.page_requested)

        navigation.workflow_buttons[1].click()

        self.assertEqual(requested.at(0)[0], 2)
        self.assertEqual(navigation.button_group.checkedId(), 2)
        self.assertEqual(navigation.library_button.objectName(), "LibraryNavButton")
        self.assertTrue(
            all(button.objectName() == "WorkflowNavButton" for button in navigation.workflow_buttons)
        )
        navigation.set_current_page(0)
        self.assertTrue(navigation.library_button.isChecked())
        navigation.close()


if __name__ == "__main__":
    unittest.main()
