from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget

from jang_app.qt_app.overflow_title_label import OverflowTextLabel
from jang_app.qt_app.processing_queue_panel import (
    ProcessingQueueButton,
    ProcessingQueuePanel,
    ProcessingTaskRow,
)
from jang_app.qt_app.window_lifecycle import WindowLifecycleGuard
from jang_app.services.i18n import tr
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

    def test_titlebar_button_tracks_queue_without_opening_a_panel(self) -> None:
        queue = ProcessingQueue()
        host = QWidget()
        layout = QVBoxLayout(host)
        button = ProcessingQueueButton(queue, parent=host)
        layout.addWidget(button)
        host.show()
        self.app.processEvents()

        self.assertTrue(button.isVisible())
        self.assertEqual((button.width(), button.height()), (48, 26))
        task_id = queue.start("Separate Audio", progress=20)
        self.app.processEvents()

        self.assertTrue(button.isVisible())
        self.assertEqual((button.width(), button.height()), (184, 26))
        self.assertEqual(button.active_count(), 1)
        self.assertEqual(button.task_count(), 1)
        self.assertEqual(button.aggregate_progress(), 20)
        self.assertEqual(button.active_title(), tr("Separate Audio"))
        self.assertIn("(1)", button.toolTip())

        queue.update_progress(task_id, 70)
        self.assertEqual(button.aggregate_progress(), 70)
        queue.complete(task_id)
        self.assertEqual(button.active_count(), 0)
        self.assertEqual((button.width(), button.height()), (48, 26))
        self.assertTrue(button.isVisible())

        queue.clear_finished()
        self.app.processEvents()
        self.assertTrue(button.isVisible())
        self.assertEqual(button.task_count(), 0)
        self.assertNotIn("(0)", button.toolTip())
        host.close()

    def test_queue_panel_uses_owned_tool_window_above_native_video(self) -> None:
        host = QWidget()
        panel = ProcessingQueuePanel(ProcessingQueue(), parent=host)

        self.assertTrue(panel.isWindow())
        self.assertTrue(panel.windowFlags() & Qt.WindowType.Tool)
        self.assertTrue(panel.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(panel.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertTrue(WindowLifecycleGuard.is_expected_window(panel))

        panel.close()
        host.close()


if __name__ == "__main__":
    unittest.main()
