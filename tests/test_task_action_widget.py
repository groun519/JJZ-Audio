from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.widgets import TaskActionWidget


class TaskActionWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_running_state_cannot_be_overridden_by_capability_refresh(self) -> None:
        action = TaskActionWidget("Task", "Run")
        action.set_running(True)

        action.set_action_enabled(True)

        self.assertFalse(action.button.isEnabled())
        action.set_running(False)
        self.assertTrue(action.button.isEnabled())
        action.set_action_enabled(False)
        self.assertFalse(action.button.isEnabled())
        action.close()


if __name__ == "__main__":
    unittest.main()
