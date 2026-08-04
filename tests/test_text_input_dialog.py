from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from jang_app.qt_app.text_input_dialog import TextInputDialog


class TextInputDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_valid_text_accepts_from_shared_app_dialog(self) -> None:
        dialog = TextInputDialog(
            "New Model",
            "Model Name",
            Path(),
            theme_mode="dark",
            accept_label="Create",
            cancel_label="Cancel",
        )

        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(dialog.title_bar.objectName(), "WindowTitleBar")
        self.assertTrue(dialog.title_bar.minimize_button.isHidden())
        self.assertTrue(dialog.title_bar.maximize_button.isHidden())
        self.assertFalse(dialog.accept_button.isEnabled())

        dialog.input_edit.setText("  Voice One  ")
        dialog.accept_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.text_value(), "Voice One")
        dialog.close()

    def test_blank_text_cannot_accept(self) -> None:
        dialog = TextInputDialog(
            "New Model",
            "Model Name",
            Path(),
            theme_mode="white",
            accept_label="Create",
            cancel_label="Cancel",
        )

        dialog.input_edit.setText("   ")
        dialog._accept_if_valid()

        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
