from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QSizePolicy

from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.processing_queue_panel import ProcessingTaskRow
from jang_app.services.processing_queue import ProcessingQueue


class ProcessingTaskRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_long_detail_uses_shared_overflow_treatment(self) -> None:
        queue = ProcessingQueue()
        detail = "A long processing detail that should stay inside the compact queue card"
        queue.start("Convert Vocal", detail)
        row = ProcessingTaskRow(queue.tasks()[0])
        row.resize(340, 70)
        row.show()
        self.app.processEvents()

        self.assertIsInstance(row.detail_label, OverflowTextLabel)
        self.assertEqual(row.detail_label.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.assertLess(row.detail_label.width(), row.detail_label.fontMetrics().horizontalAdvance(detail))
        self.assertEqual(row.detail_label.toolTip(), detail)
        row.close()


if __name__ == "__main__":
    unittest.main()
