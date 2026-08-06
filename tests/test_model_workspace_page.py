from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_add_dialog import (
    ModelAddAction,
    ModelAddRequest,
    ModelImportMode,
    ModelImportSource,
)
from jang_app.qt_app.model_workspace import ModelWorkspacePage
from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.model_dataset import ModelDataset, ModelDatasetItem
from jang_app.services.processing_queue import ProcessingQueue, TASK_COMPLETED
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.rvc_training_pipeline import RvcTrainingStage
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
            self.assertEqual(page.workspace_content_stack.count(), 4)
            page.training_section_button.click()
            self.assertEqual(page.workspace_content_stack.currentIndex(), 3)
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

    def test_training_updates_global_processing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.create_model("Voice One", root / "rvc")
            queue = ProcessingQueue()
            execution_runtime = root / "managed-rvc"
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


if __name__ == "__main__":
    unittest.main()
