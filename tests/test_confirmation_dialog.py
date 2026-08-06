from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from jang_app.qt_app.confirmation_dialog import ConfirmationDialog


class ConfirmationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_destructive_confirmation_uses_shared_app_chrome(self) -> None:
        dialog = ConfirmationDialog(
            "Remove Vocal Result",
            "This cannot be undone.",
            Path(),
            theme_mode="dark",
            accept_label="Remove",
            cancel_label="Cancel",
        )

        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(dialog.title_bar.objectName(), "WindowTitleBar")
        accept_button = dialog.findChild(QPushButton, "DangerButton")
        self.assertIsNotNone(accept_button)
        accept_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
