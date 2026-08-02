from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.services.rvc_model_workspace import RvcModelWorkspace


class ModelWorkspacePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_new_model_button_creates_model_and_opens_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            page = ModelWorkspacePage(root / "rvc", workspace)

            with patch(
                "jang_app.qt_app.model_workspace.QInputDialog.getText",
                return_value=("Voice One", True),
            ):
                page.new_model_button.click()

            records = workspace.records()
            self.assertEqual([record.name for record in records], ["Voice One"])
            self.assertEqual(page.view_stack.currentIndex(), 1)
            self.assertEqual(page.workspace_content_stack.currentIndex(), 1)
            page.close()


if __name__ == "__main__":
    unittest.main()
