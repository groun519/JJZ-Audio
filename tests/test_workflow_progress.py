from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.workflow_progress import WorkflowProgress, WorkflowStage


class WorkflowProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_marks_completed_active_and_pending_stages(self) -> None:
        progress = WorkflowProgress(
            (
                WorkflowStage("prepare", "Prepare"),
                WorkflowStage("train", "Train"),
                WorkflowStage("index", "Index"),
            )
        )

        progress.set_status("train", completed_keys=("prepare",))

        self.assertEqual(progress.stage_state("prepare"), "complete")
        self.assertEqual(progress.stage_state("train"), "active")
        self.assertEqual(progress.stage_state("index"), "pending")
        self.assertEqual(progress.connectors[0].property("stageState"), "complete")
        progress.close()

    def test_marks_only_active_stage_as_failed(self) -> None:
        progress = WorkflowProgress(
            (
                WorkflowStage("prepare", "Prepare"),
                WorkflowStage("train", "Train"),
            )
        )

        progress.set_status("train", completed_keys=("prepare",), failed=True)

        self.assertEqual(progress.stage_state("prepare"), "complete")
        self.assertEqual(progress.stage_state("train"), "failed")
        progress.close()


if __name__ == "__main__":
    unittest.main()
