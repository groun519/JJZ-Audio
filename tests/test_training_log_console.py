from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.training_log_console import TrainingLogConsole


class TrainingLogConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_filters_errors_without_losing_raw_lines(self) -> None:
        console = TrainingLogConsole()
        console.append_batch("Train Epoch: 2 [30%]\nRuntimeError: CUDA out of memory")
        console._flush_pending()

        console.filter_combo.setCurrentIndex(console.filter_combo.findData("error"))

        self.assertNotIn("Train Epoch", console.output.toPlainText())
        self.assertIn("CUDA out of memory", console.output.toPlainText())
        self.assertEqual(len(console._lines), 2)
        console.close()

    def test_paused_auto_scroll_reports_new_lines(self) -> None:
        console = TrainingLogConsole()
        console.auto_scroll_button.setChecked(False)

        console.append_batch("first\nsecond")
        console._flush_pending()

        self.assertEqual(console._new_line_count, 2)
        self.assertFalse(console.new_lines_label.isHidden())
        console.auto_scroll_button.setChecked(True)
        self.assertEqual(console._new_line_count, 0)
        console.close()


if __name__ == "__main__":
    unittest.main()
