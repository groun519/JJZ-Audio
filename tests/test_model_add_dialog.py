from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QDialog

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.model_add_dialog import (
    ModelAddAction,
    ModelAddDialog,
    ModelImportMode,
    ModelImportSource,
)


class ModelAddDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_create_choice_returns_create_request(self) -> None:
        dialog = ModelAddDialog(APP_ICON_PATH, theme_mode="dark")

        dialog.create_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(dialog.request())
        self.assertEqual(dialog.request().action, ModelAddAction.CREATE)
        dialog.close()

    def test_import_choice_returns_selected_source_and_mode(self) -> None:
        dialog = ModelAddDialog(APP_ICON_PATH, theme_mode="dark")

        dialog.existing_button.click()
        dialog.folder_source_button.click()
        dialog.linked_mode_button.click()
        dialog.import_button.click()

        request = dialog.request()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(request)
        self.assertEqual(request.action, ModelAddAction.IMPORT)
        self.assertEqual(request.source, ModelImportSource.RVC_FOLDER)
        self.assertEqual(request.mode, ModelImportMode.LINKED)
        dialog.close()

    def test_drive_link_choice_returns_managed_link_request(self) -> None:
        dialog = ModelAddDialog(APP_ICON_PATH, theme_mode="dark")

        dialog.drive_button.click()
        dialog.drive_link_edit.setText("https://drive.google.com/file/d/1234567890abc/view")
        dialog.drive_import_button.click()

        request = dialog.request()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(request)
        self.assertEqual(request.source, ModelImportSource.DRIVE_LINK)
        self.assertEqual(request.mode, ModelImportMode.MANAGED)
        self.assertIn("drive.google.com", request.link)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
