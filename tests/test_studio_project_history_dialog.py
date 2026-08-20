from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_project_history_dialog import StudioProjectHistoryDialog
from jang_app.services.i18n import set_language
from jang_app.services.studio_project import StudioProjectRevision


class StudioProjectHistoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language("ko")

    def tearDown(self) -> None:
        set_language("ko")

    def test_current_revision_is_labeled_and_cannot_be_restored(self) -> None:
        dialog = StudioProjectHistoryDialog(
            (
                StudioProjectRevision(2, "2026-08-20T12:00:00+00:00", 3, 8),
                StudioProjectRevision(1, "2026-08-20T11:00:00+00:00", 3, 6),
            ),
            Path("missing.ico"),
            theme_mode="dark",
        )

        self.assertIn("현재", dialog.revision_list.item(0).text())
        self.assertFalse(dialog.restore_button.isEnabled())
        dialog.revision_list.setCurrentRow(1)
        self.assertTrue(dialog.restore_button.isEnabled())

        dialog.close()


if __name__ == "__main__":
    unittest.main()
