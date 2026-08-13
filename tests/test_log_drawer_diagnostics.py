from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.log_drawer import LogDrawer
from jang_app.services.job_diagnostics import JobDiagnostics
from jang_app.services.processing_queue import ProcessingQueue


class LogDrawerDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selected_task_exposes_copyable_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="drawer-test")
            queue = ProcessingQueue(diagnostics=diagnostics)
            task_id = queue.start("Convert Vocal", "song.wav")
            queue.fail(task_id, "CUDA out of memory")
            drawer = LogDrawer(queue)

            drawer.refresh_content()
            drawer.select_task(task_id)
            drawer._copy_selected_diagnostics()

            self.assertTrue(drawer.copy_diagnostics_button.isEnabled())
            self.assertIn(f"Task ID: {task_id}", QApplication.clipboard().text())
            self.assertIn("CUDA_OUT_OF_MEMORY", drawer.activity_detail.toPlainText())
            drawer.close()

    def test_header_can_return_to_processing_queue(self) -> None:
        drawer = LogDrawer(ProcessingQueue())
        requests: list[bool] = []
        drawer.queue_requested.connect(lambda: requests.append(True))

        drawer.queue_button.click()

        self.assertEqual(requests, [True])
        self.assertTrue(drawer.queue_button.toolTip())
        drawer.close()


if __name__ == "__main__":
    unittest.main()
