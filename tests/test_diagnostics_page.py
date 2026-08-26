from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.diagnostics_page import (
    DiagnosticsPage,
    DiagnosticsWindow,
)
from jang_app.services.i18n import tr
from jang_app.services.job_diagnostics import JobDiagnostics
from jang_app.services.processing_queue import ProcessingQueue
from jang_app.services.storage_management import CleanupCandidate, StorageCleanupPlan


class DiagnosticsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_restores_failed_job_and_exposes_diagnostic_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = JobDiagnostics(root, session_id="first")
            first_queue = ProcessingQueue(diagnostics=first)
            task_id = first_queue.start("Train Model", "voice\nwith extra detail")
            first.append_command_output(task_id, "training output")
            first_queue.fail(task_id, "CUDA out of memory")

            restored = JobDiagnostics(root, session_id="restored")
            page = DiagnosticsPage(ProcessingQueue(diagnostics=restored), restored)
            page.open_task(task_id)
            page.resize(900, 620)
            page.show()
            self.app.processEvents()

            self.assertEqual(page.selected_task_id(), task_id)
            self.assertIn("CUDA_OUT_OF_MEMORY", page.summary_text.toPlainText())
            self.assertIn("training output", page.command_log_text.toPlainText())
            self.assertTrue(page.package_button.isEnabled())
            item = page.history_list.item(0)
            row = page.history_list.itemWidget(item)
            self.assertEqual(item.sizeHint().height(), 70)
            self.assertEqual(row.height(), 64)
            self.assertEqual(row.detail_label.height(), 15)
            self.assertNotIn("\n", row.detail_label.toolTip())
            self.assertEqual(item.text(), "")
            self.assertEqual(
                item.data(Qt.ItemDataRole.AccessibleTextRole),
                tr("Train Model"),
            )

            page._copy_selected_report()
            self.assertIn(task_id, QApplication.clipboard().text())
            page.close()

    def test_filters_persisted_jobs_without_removing_the_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="filter")
            queue = ProcessingQueue(diagnostics=diagnostics)
            failed_id = queue.start("Train Model", "voice")
            queue.fail(failed_id, "CUDA out of memory")
            completed_id = queue.start("Separate Audio", "song")
            queue.complete(completed_id)
            page = DiagnosticsPage(queue, diagnostics)

            page.status_combo.setCurrentIndex(page.status_combo.findData("failed"))

            self.assertEqual(page.history_list.count(), 1)
            self.assertEqual(
                page.history_list.item(0).data(Qt.ItemDataRole.UserRole),
                failed_id,
            )
            self.assertEqual(len(page._tasks), 2)
            page.close()

    def test_page_is_embedded_and_system_recheck_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="system")
            host = QWidget()
            page = DiagnosticsPage(
                ProcessingQueue(diagnostics=diagnostics),
                diagnostics,
                parent=host,
            )
            requests: list[bool] = []
            page.system_setup_requested.connect(lambda: requests.append(True))
            page.apply_language()

            page.run_system_diagnostics_button.click()

            self.assertFalse(page.isWindow())
            self.assertEqual(len(page.navigation_buttons), 5)
            self.assertEqual(page.page_stack.count(), 5)
            self.assertEqual(requests, [True])
            self.assertEqual(page.open_logs_button.text(), "")
            self.assertEqual(page.open_logs_button.toolTip(), tr("Open Log Folder"))
            self.assertEqual(page.refresh_button.text(), "")
            self.assertEqual(page.refresh_button.toolTip(), tr("Refresh"))
            self.assertEqual(page.support_button.text(), tr("Create Diagnostics ZIP"))

            page.resize(900, 620)
            page._apply_responsive_layout()
            self.assertTrue(page._navigation_compact)
            self.assertEqual(page.navigation_frame.width(), 62)

            page.resize(1200, 700)
            page._apply_responsive_layout()
            self.assertFalse(page._navigation_compact)
            self.assertEqual(page.navigation_frame.width(), 202)
            page.close()
            host.close()

    def test_window_is_modeless_resizable_and_reuses_its_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="window")
            queue = ProcessingQueue(diagnostics=diagnostics)
            window = DiagnosticsWindow(queue, diagnostics)
            page = window.page

            window.show_diagnostics()
            self.app.processEvents()

            self.assertTrue(window.isWindow())
            self.assertFalse(window.isModal())
            self.assertTrue(window.isVisible())
            self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertTrue(window.title_bar.isVisible())
            self.assertFalse(page.back_button.isVisible())
            self.assertEqual(window.minimumWidth(), 760)
            self.assertEqual(window.windowTitle(), tr("Environment & Management"))
            self.assertEqual(page.title_label.text(), tr("Environment & Management"))

            window.close()
            self.app.processEvents()
            window.show_diagnostics()
            self.app.processEvents()

            self.assertIs(window.page, page)
            self.assertTrue(window.isVisible())
            window.close()

    def test_queue_change_invalidates_a_cached_cleanup_plan_while_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostics = JobDiagnostics(root / "logs", session_id="cleanup")
            queue = ProcessingQueue(diagnostics=diagnostics)
            page = DiagnosticsPage(queue, diagnostics)
            candidate = CleanupCandidate(
                "Temporary jobs",
                root / "cache" / "task",
                root / "cache",
                10,
                1,
                requires_idle=True,
            )
            page._cleanup_plan = StorageCleanupPlan((candidate,))
            page.storage_panel.set_cleanup_plan(page._cleanup_plan)

            queue.start("Train Model", "voice")

            self.assertFalse(page._cleanup_plan.candidates)
            self.assertFalse(page.storage_panel.cleanup_button.isEnabled())
            page.close()

if __name__ == "__main__":
    unittest.main()
