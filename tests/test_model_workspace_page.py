from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.model_add_dialog import (
    ModelAddAction,
    ModelAddRequest,
    ModelImportMode,
    ModelImportSource,
)
from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.qt_app.theme import build_stylesheet
from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.i18n import tr
from jang_app.services.model_dataset import ModelDataset, ModelDatasetItem
from jang_app.services.processing_queue import (
    ProcessingQueue,
    TASK_COMPLETED,
    TASK_FAILED,
)
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.rvc_training_pipeline import RvcTrainingStage
from jang_app.services.rvc_training_preflight import RvcTrainingPreflight
from jang_app.services.rvc_training_preprocess import RvcTrainingPreprocessFailure
from jang_app.services.rvc_training_runtime import required_rvc_training_paths
from jang_app.services.rvc_training_state import RvcTrainingStateStore
from jang_app.services.rvc_training_train import RvcTrainingRunSettings


class ModelWorkspacePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_new_model_button_creates_model_and_opens_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            page = ModelWorkspacePage(root / "rvc", workspace)
            changes: list[bool] = []
            page.models_changed.connect(lambda: changes.append(True))

            with (
                patch(
                    "jang_app.qt_app.model_workspace.ModelAddDialog.get_request",
                    return_value=ModelAddRequest(ModelAddAction.CREATE),
                ),
                patch(
                    "jang_app.qt_app.model_workspace.TextInputDialog.get_text",
                    return_value=("Voice One", True),
                ),
            ):
                page.add_model_button.click()

            records = workspace.records()
            self.assertEqual([record.name for record in records], ["Voice One"])
            self.assertEqual(page.view_stack.currentIndex(), 1)
            self.assertEqual(page.workspace_content_stack.currentIndex(), 1)
            self.assertEqual(page.workspace_content_stack.count(), 5)
            self.assertEqual(changes, [True])
            page.training_section_button.click()
            self.assertEqual(page.workspace_content_stack.currentIndex(), 4)
            page.close()

    def test_model_library_search_filter_and_count_preserve_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            managed = workspace.create_model("Managed Voice", root / "rvc")
            inference_file = root / "linked_voice.pth"
            inference_file.write_bytes(b"inference")
            linked = workspace.link_inference_file(inference_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            items = {}
            for index in range(page.model_list.count()):
                item = page.model_list.item(index)
                items[item.data(Qt.ItemDataRole.UserRole)] = item

            self.assertEqual(page.model_library_count_label.text(), "2 / 2")

            page.model_search_edit.setText("managed voice")
            self.assertFalse(items[managed.model_id].isHidden())
            self.assertTrue(items[linked.model_id].isHidden())
            self.assertEqual(page.model_library_count_label.text(), "1 / 2")

            page.model_search_edit.clear()
            page.model_filter_combo.setCurrentIndex(
                page.model_filter_combo.findData("linked")
            )
            self.assertTrue(items[managed.model_id].isHidden())
            self.assertFalse(items[linked.model_id].isHidden())

            page.model_filter_combo.setCurrentIndex(
                page.model_filter_combo.findData("convert")
            )
            self.assertTrue(items[managed.model_id].isHidden())
            self.assertFalse(items[linked.model_id].isHidden())

            page.model_filter_combo.setCurrentIndex(
                page.model_filter_combo.findData("attention")
            )
            self.assertFalse(items[managed.model_id].isHidden())
            self.assertTrue(items[linked.model_id].isHidden())
            self.assertEqual(len(page._rows_by_id), 2)
            page.close()

    def test_excluded_preprocess_input_opens_its_original_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = ModelWorkspacePage(root / "rvc", RvcModelWorkspace(root / "models"))
            failure = RvcTrainingPreprocessFailure(
                "0016_voice.wav",
                "ValueError: clip is too short",
                "item-1",
                "clip-16",
            )

            with patch.object(page, "_open_dataset_item") as opened:
                page._open_excluded_training_clip(failure)

            opened.assert_called_once_with("item-1", "clip-16")
            page.close()

    def test_opening_selected_model_does_not_reload_every_panel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            page = ModelWorkspacePage(root / "rvc", workspace)
            self.assertEqual(page._selected_model_id, record.model_id)

            with (
                patch.object(page.detail_panel, "set_record") as detail,
                patch.object(page.dataset_panel, "set_model") as dataset,
                patch.object(page.analysis_panel, "set_model") as analysis,
                patch.object(page.evaluation_panel, "set_model") as evaluation,
                patch.object(page, "_refresh_training_panel") as training,
            ):
                page._open_model(record.model_id)

            detail.assert_not_called()
            dataset.assert_not_called()
            analysis.assert_not_called()
            evaluation.assert_not_called()
            training.assert_not_called()
            self.assertEqual(page.view_stack.currentIndex(), 1)
            page.close()

    def test_model_selection_defers_material_and_training_panels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            workspace.create_model("Voice One", root / "rvc")
            workspace.create_model("Voice Two", root / "rvc")
            page = ModelWorkspacePage(root / "rvc", workspace)

            with (
                patch.object(page.dataset_panel, "set_model") as dataset,
                patch.object(page.analysis_panel, "set_model") as analysis,
                patch.object(page.evaluation_panel, "set_model") as evaluation,
                patch.object(page, "_refresh_training_panel") as training,
            ):
                page.model_list.setCurrentRow(1)

            dataset.assert_not_called()
            analysis.assert_not_called()
            evaluation.assert_not_called()
            training.assert_not_called()
            page.close()

    def test_model_dataset_is_loaded_once_and_reused_by_heavy_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            page = ModelWorkspacePage(root / "rvc", workspace)

            with patch.object(
                page._dataset_store,
                "load",
                wraps=page._dataset_store.load,
            ) as load:
                page._open_model(record.model_id)
                self.app.processEvents()
                worker = page._dataset_load_worker
                self.assertIsNotNone(worker)
                worker.wait()
                self.app.processEvents()

                page._navigate_model_section(1)
                self.app.processEvents()
                page._navigate_model_section(4)

            self.assertEqual(load.call_count, 1)
            self.assertEqual(page._loaded_dataset.model_id, record.model_id)
            page.close()

    def test_model_page_does_not_probe_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")

            with (
                patch(
                    "jang_app.services.rvc_runtime_profile._run_nvidia_smi"
                ) as nvidia_probe,
                patch(
                    "jang_app.services.rvc_hardware._run_powershell"
                ) as adapter_probe,
            ):
                page = ModelWorkspacePage(root / "rvc", workspace)

            nvidia_probe.assert_not_called()
            adapter_probe.assert_not_called()
            page.close()

    def test_model_navigation_never_shows_temporary_child_windows(self) -> None:
        unexpected: list[str] = []

        class WindowShowProbe(QObject):
            def eventFilter(self, watched, event):  # noqa: N802
                if (
                    event.type() == QEvent.Type.Show
                    and isinstance(watched, QWidget)
                    and watched.isWindow()
                ):
                    unexpected.append(
                        f"{type(watched).__name__}:{watched.objectName()}:{watched.windowTitle()}"
                    )
                return False

        probe = WindowShowProbe()
        self.app.installEventFilter(probe)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = RvcModelWorkspace(root / "models")
                record = workspace.create_model("Voice One", root / "rvc")
                page = ModelWorkspacePage(root / "rvc", workspace)
                with patch.object(page.analysis_panel, "ensure_analysis"):
                    page._open_model(record.model_id)
                    for section in range(page.workspace_content_stack.count()):
                        page._navigate_model_section(section)
                        self.app.processEvents()
                page.close()
        finally:
            self.app.removeEventFilter(probe)

        self.assertEqual(unexpected, [])

    def test_precision_evaluation_updates_processing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            queue = ProcessingQueue()
            page = ModelWorkspacePage(root / "rvc", workspace, processing_queue=queue)

            page.evaluation_panel.benchmark_started.emit(record.model_id, record.title)
            tasks = queue.tasks()
            self.assertEqual(len(tasks), 1)
            task_id = tasks[0].task_id
            self.assertEqual(tasks[0].title, tr("Model Evaluation"))
            self.assertEqual(tasks[0].detail, record.title)

            page.evaluation_panel.benchmark_progress_reported.emit(
                44,
                tr("Preparing precise evaluation..."),
            )
            tasks = queue.tasks()
            self.assertEqual(tasks[0].task_id, task_id)
            self.assertEqual(tasks[0].progress, 44)
            self.assertIn(record.title, tasks[0].detail)

            page.evaluation_panel.benchmark_completed.emit(record.model_id, record.title)
            tasks = queue.tasks()
            self.assertEqual(tasks[0].status, TASK_COMPLETED)

            page.evaluation_panel.benchmark_finished_reported.emit(record.model_id, record.title)
            self.assertEqual(page._benchmark_task_id, "")
            self.assertEqual(page._benchmark_model_id, "")
            self.assertEqual(page._benchmark_model_title, "")
            page.close()

    def test_precision_evaluation_failure_updates_processing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            queue = ProcessingQueue()
            page = ModelWorkspacePage(root / "rvc", workspace, processing_queue=queue)

            page.evaluation_panel.benchmark_started.emit(record.model_id, record.title)
            page.evaluation_panel.benchmark_failed_reported.emit(
                record.model_id,
                record.title,
                "Traceback",
            )

            tasks = queue.tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].status, TASK_FAILED)
            self.assertEqual(tasks[0].error, "Traceback")
            page.close()

    def test_add_model_dialog_routes_linked_inference_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            page = ModelWorkspacePage(root / "rvc", workspace)

            request = ModelAddRequest(
                ModelAddAction.IMPORT,
                ModelImportSource.INFERENCE_FILE,
                ModelImportMode.LINKED,
            )
            with (
                patch(
                    "jang_app.qt_app.model_workspace.ModelAddDialog.get_request",
                    return_value=request,
                ),
                patch(
                    "jang_app.qt_app.model_workspace.QFileDialog.getOpenFileName",
                    return_value=(str(model_file), ""),
                ),
            ):
                page.add_model_button.click()

            records = workspace.records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].inference_model, model_file.resolve())
            self.assertTrue(records[0].can_convert)
            page.close()

    def test_add_model_dialog_routes_drive_link_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            page = ModelWorkspacePage(root / "rvc", workspace)
            requested: list[str] = []
            page.drive_import_requested.connect(requested.append)
            link = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"

            with patch(
                "jang_app.qt_app.model_workspace.ModelAddDialog.get_request",
                return_value=ModelAddRequest(
                    ModelAddAction.IMPORT,
                    ModelImportSource.DRIVE_LINK,
                    ModelImportMode.MANAGED,
                    link,
                ),
            ):
                page.add_model_button.click()

            self.assertEqual(requested, [link])
            page.close()

    def test_selected_inference_model_can_be_shared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            shared: list[object] = []
            page.share_requested.connect(shared.append)
            row = page._rows_by_id[record.model_id]

            self.assertTrue(row.share_button.isHidden())
            row.enterEvent(
                QEnterEvent(
                    QPointF(1, 1),
                    QPointF(1, 1),
                    QPointF(1, 1),
                )
            )
            self.assertFalse(row.share_button.isHidden())
            self.assertTrue(row.share_action.progress_bar.isHidden())
            self.assertTrue(row.share_action.progress_label.isHidden())
            row.share_button.click()
            row.leaveEvent(QEvent(QEvent.Type.Leave))

            self.assertEqual(shared, [record])
            self.assertTrue(row.share_button.isHidden())
            page.close()

    def test_model_row_removes_model_and_training_work_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            work_dir = workspace.root / record.model_id
            work_dir.mkdir(parents=True)
            (work_dir / "dataset.json").write_text("{}", encoding="utf-8")
            page = ModelWorkspacePage(root / "rvc", workspace)
            row = page._rows_by_id[record.model_id]

            row.enterEvent(
                QEnterEvent(
                    QPointF(1, 1),
                    QPointF(1, 1),
                    QPointF(1, 1),
                )
            )
            self.assertFalse(row.remove_button.isHidden())
            with patch(
                "jang_app.qt_app.model_workspace.ConfirmationDialog.confirm",
                return_value=True,
            ):
                row.remove_button.click()

            self.assertEqual(workspace.records(), [])
            self.assertFalse(work_dir.exists())
            self.assertNotIn(record.model_id, page._rows_by_id)
            self.assertEqual(page.status_label.text(), tr("Model deleted."))
            page.close()

    def test_selected_managed_model_can_request_work_share(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            page = ModelWorkspacePage(root / "rvc", workspace)
            shared: list[object] = []
            page.work_share_requested.connect(shared.append)

            page._open_model(record.model_id)
            self.assertEqual(
                page.workspace_work_share_action.button.text(),
                tr("Share Work"),
            )
            page.workspace_work_share_action.button.click()

            self.assertEqual(shared, [record])
            page.workspace_work_share_action.set_shared(True)
            self.assertEqual(
                page.workspace_work_share_action.button.text(),
                tr("Work Link"),
            )
            page.close()

    def test_model_share_progress_replaces_redundant_badges_inline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            row = page._rows_by_id[record.model_id]

            self.assertEqual(row.share_button.text(), "")

            page.set_share_started(record.model_id)
            page.set_share_progress(record.model_id, 46)

            self.assertIn(tr(record.status_label), row.detail_label.text())
            self.assertIn(tr(record.mode_label), row.detail_label.text())
            self.assertFalse(row.share_action.progress_bar.isHidden())
            self.assertEqual(row.share_action.progress_bar.value(), 46)
            self.assertEqual(row.share_action.progress_label.text(), "46%")
            self.assertTrue(row.share_button.isHidden())

            page.set_share_failed(record.model_id)
            self.assertTrue(row.share_action.progress_bar.isHidden())
            page.close()

    def test_model_share_completion_confirms_copy_without_clipping_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            row = page._rows_by_id[record.model_id]

            page.set_share_completed(record.model_id)

            self.assertEqual(row.share_action.copied_label.text(), tr("Copied"))
            self.assertFalse(row.share_action.copied_label.isHidden())
            self.assertTrue(row.share_button.isHidden())
            self.assertEqual(row.share_button.width(), 36)
            self.assertEqual(row.share_action.delete_button.width(), 36)
            self.assertGreater(row.share_action.height(), row.share_button.height())
            self.assertGreater(row.share_action.height(), row.share_action.delete_button.height())
            page.close()

    def test_shared_model_is_marked_and_exposes_drive_delete_on_hover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            deleted: list[object] = []
            page.delete_share_requested.connect(deleted.append)
            page.set_share_status_provider(lambda _record: True)
            row = page._rows_by_id[record.model_id]

            self.assertEqual(row.share_button.icon_name(), "cloud_check")
            self.assertFalse(row.share_action.isHidden())
            self.assertTrue(row.share_action.delete_button.isHidden())

            row.enterEvent(
                QEnterEvent(
                    QPointF(1, 1),
                    QPointF(1, 1),
                    QPointF(1, 1),
                )
            )
            row.share_action.delete_button.click()

            self.assertEqual(deleted, [record])
            page.set_share_deleted(record.model_id)
            row.leaveEvent(QEvent(QEvent.Type.Leave))
            self.assertEqual(row.share_button.icon_name(), "link")
            self.assertFalse(row.share_action.isHidden())
            self.assertTrue(row.share_button.isHidden())
            page.close()

    def test_model_share_action_stays_hidden_when_feature_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            shared: list[object] = []
            page.share_requested.connect(shared.append)
            row = page._rows_by_id[record.model_id]
            page.set_sharing_enabled(False)

            row.enterEvent(
                QEnterEvent(
                    QPointF(1, 1),
                    QPointF(1, 1),
                    QPointF(1, 1),
                )
            )
            row.share_button.click()
            page._emit_share_model(record.model_id)

            self.assertTrue(row.share_button.isHidden())
            self.assertFalse(row.share_button.isEnabled())
            self.assertEqual(shared, [])
            page.close()

    def test_hidden_model_share_slot_renders_as_row_background(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            page = ModelWorkspacePage(root / "rvc", workspace)
            row = page._rows_by_id[record.model_id]
            row.setStyleSheet(build_stylesheet("dark"))
            row.resize(620, row.sizeHint().height())
            row.show()
            self.app.processEvents()

            image = row.grab().toImage()
            slot_center = row.action_slot.geometry().center()
            slot_color = image.pixelColor(slot_center)
            row_color = image.pixelColor(10, slot_center.y())

            self.assertEqual(slot_color, row_color)
            row.close()
            page.close()

    def test_training_updates_global_processing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            queue = ProcessingQueue()
            execution_runtime = root / "managed-rvc"
            _create_training_runtime(execution_runtime)
            page = ModelWorkspacePage(
                root / "rvc",
                workspace,
                queue,
                execution_runtime,
            )
            page._open_model(record.model_id)
            dataset = ModelDataset(record.model_id, (_ready_dataset_item(root),))

            pipeline_roots: list[Path] = []

            def run_pipeline(*args, progress, stage_callback, **_kwargs):
                pipeline_roots.append(args[2])
                stage_callback(RvcTrainingStage.TRAIN)
                progress(72)
                return SimpleNamespace(stopped=False)

            with (
                patch("jang_app.qt_app.model_workspace.ModelDatasetStore.load", return_value=dataset),
                patch(
                    "jang_app.qt_app.model_workspace.inspect_rvc_training_preflight",
                    return_value=RvcTrainingPreflight(()),
                ),
                patch("jang_app.qt_app.model_workspace.run_rvc_training_pipeline", side_effect=run_pipeline),
                patch(
                    "jang_app.qt_app.model_workspace.finalize_rvc_training_artifacts",
                    return_value=SimpleNamespace(record=record),
                ),
            ):
                page._start_training(RvcTrainingRunSettings(target_epoch=20))
                worker = page._training_worker
                self.assertIsNotNone(worker)
                worker.wait()
                self.app.processEvents()
                self.app.processEvents()

            task = queue.tasks()[0]
            self.assertEqual(task.status, TASK_COMPLETED)
            self.assertEqual(task.progress, 100)
            self.assertEqual(pipeline_roots, [execution_runtime.resolve()])
            self.assertIsNone(page._training_worker)
            page.close()

    def test_training_failure_persists_recovery_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            queue = ProcessingQueue()
            page = ModelWorkspacePage(root / "rvc", workspace, queue)
            page._open_model(record.model_id)
            task_id = queue.start("Train RVC Model", record.title)
            page._training_model_id = record.model_id
            page._training_task_id = task_id
            requested_logs: list[str] = []
            page.log_requested.connect(requested_logs.append)

            page._on_training_failed("RuntimeError: CUDA out of memory")
            page.training_panel.recovery_diagnostics_button.click()

            state = RvcTrainingStateStore(
                record.model_id,
                page._training_layout(record),
            ).load()
            self.assertEqual(state.last_task_id, task_id)
            self.assertEqual(
                state.last_diagnostic_code,
                "CUDA_OUT_OF_MEMORY",
            )
            self.assertFalse(page.training_panel.recovery_card.isHidden())
            self.assertEqual(requested_logs, [task_id])
            page.close()


def _ready_dataset_item(root: Path) -> ModelDatasetItem:
    audio = root / "voice.wav"
    audio.write_bytes(b"audio")
    return ModelDatasetItem(
        item_id="item-1",
        source_name="voice.wav",
        source_path=audio,
        original_path=audio,
        working_path=audio,
        added_at="2026-01-01T00:00:00+00:00",
        duration_ms=1000,
        selected_order=0,
        review_state=REVIEW_READY,
    )


def _create_training_runtime(root: Path) -> None:
    for relative_path in required_rvc_training_paths():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")


if __name__ == "__main__":
    unittest.main()
