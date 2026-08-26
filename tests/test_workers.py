from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import MainWindow
from jang_app.qt_app.workers import TaskWorker
from jang_app.services.processing_queue import ProcessingQueue, TASK_FAILED


class TaskWorkerOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_resource_owner_is_explicit(self) -> None:
        worker = TaskWorker(lambda _progress: None)
        worker.set_resource_owner("song", "song-1")

        self.assertTrue(worker.owns_resource("song", "song-1"))
        self.assertFalse(worker.owns_resource("song", "song-2"))

    def test_background_failure_is_written_to_the_application_log(self) -> None:
        worker = TaskWorker(
            lambda _progress: (_ for _ in ()).throw(RuntimeError("worker failed"))
        )
        failures: list[str] = []
        worker.failed.connect(failures.append)

        with patch("jang_app.qt_app.workers.get_logger") as get_logger:
            worker.run()

        self.assertEqual(len(failures), 1)
        self.assertIn("RuntimeError: worker failed", failures[0])
        get_logger.return_value.error.assert_called_once()
        self.assertIn(
            "RuntimeError: worker failed",
            str(get_logger.return_value.error.call_args),
        )

    def test_result_finalization_failure_marks_the_same_task_failed(self) -> None:
        queue = ProcessingQueue()
        failures: list[str] = []
        host = SimpleNamespace(
            processing_queue=queue,
            _workers=[],
            _worker_task_ids={},
            _action_task_ids={},
            _logger=Mock(),
            _closing=False,
        )
        worker = TaskWorker(lambda _progress: "result")

        MainWindow._run_worker(
            host,
            worker,
            lambda _result: (_ for _ in ()).throw(RuntimeError("finalization failed")),
            failures.append,
            None,
            task_title="Finalize Output",
        )
        self.assertTrue(worker.wait(5000))
        for _ in range(10):
            self.app.processEvents()
            QTest.qWait(1)

        task = queue.tasks()[0]
        self.assertEqual(task.status, TASK_FAILED)
        self.assertIn("finalization failed", task.error)
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
