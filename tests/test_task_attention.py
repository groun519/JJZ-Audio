from __future__ import annotations

import unittest

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.task_attention import TaskAttentionController
from jang_app.services.processing_queue import ProcessingQueue


class TaskAttentionControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_background_completion_requests_taskbar_attention(self) -> None:
        queue = ProcessingQueue()
        window = QWidget()
        alerts: list[bool] = []
        controller = TaskAttentionController(
            queue,
            window,
            alert=lambda: alerts.append(True),
            is_foreground=lambda: False,
        )

        task_id = queue.start("Separate Audio")
        queue.complete(task_id)

        self.assertEqual(alerts, [True])
        controller.close()
        window.close()

    def test_foreground_completion_does_not_request_attention(self) -> None:
        queue = ProcessingQueue()
        window = QWidget()
        alerts: list[bool] = []
        controller = TaskAttentionController(
            queue,
            window,
            alert=lambda: alerts.append(True),
            is_foreground=lambda: True,
        )

        task_id = queue.start("Convert Vocal")
        queue.complete(task_id)

        self.assertEqual(alerts, [])
        controller.close()
        window.close()

    def test_multiple_results_are_coalesced_until_attention_is_acknowledged(self) -> None:
        queue = ProcessingQueue()
        window = QWidget()
        alerts: list[bool] = []
        controller = TaskAttentionController(
            queue,
            window,
            alert=lambda: alerts.append(True),
            is_foreground=lambda: False,
        )

        first_id = queue.start("Separate Audio")
        second_id = queue.start("Convert Vocal")
        queue.complete(first_id)
        queue.fail(second_id, "conversion failed")
        self.assertEqual(alerts, [True])

        QApplication.sendEvent(window, QEvent(QEvent.Type.WindowActivate))
        third_id = queue.start("Train RVC Model")
        queue.complete(third_id)
        self.assertEqual(alerts, [True, True])

        controller.close()
        window.close()

    def test_cancelled_or_preexisting_finished_tasks_do_not_request_attention(self) -> None:
        queue = ProcessingQueue()
        completed_id = queue.start("Old task")
        queue.complete(completed_id)
        window = QWidget()
        alerts: list[bool] = []
        controller = TaskAttentionController(
            queue,
            window,
            alert=lambda: alerts.append(True),
            is_foreground=lambda: False,
        )

        cancelled_id = queue.start("Cancelled task")
        queue.cancel(cancelled_id)

        self.assertEqual(alerts, [])
        controller.close()
        window.close()


if __name__ == "__main__":
    unittest.main()
