from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_training_panel import ModelTrainingPanel, format_training_elapsed
from jang_app.services.i18n import LANGUAGE_ENGLISH, set_language
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from jang_app.services.rvc_training_train import RvcTrainingRunSettings


class ModelTrainingPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language(LANGUAGE_ENGLISH)

    def test_resume_state_emits_selected_training_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            (layout.experiment_dir / "G_120.pth").write_bytes(b"generator")
            (layout.experiment_dir / "D_120.pth").write_bytes(b"discriminator")
            state = RvcTrainingStateStore("voice", layout).refresh_checkpoint_pair()
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 2, 2)
            panel.apply_language()

            emitted: list[RvcTrainingRunSettings] = []
            panel.start_requested.connect(emitted.append)
            panel.target_epoch_spin.setValue(40)
            panel.batch_size_spin.setValue(6)
            panel.save_interval_spin.setValue(10)
            panel.gpu_index_spin.setValue(1)
            panel.start_button.click()

            self.assertEqual(panel.start_button.text(), "Resume Training")
            self.assertEqual(
                emitted,
                [
                    RvcTrainingRunSettings(
                        target_epoch=40,
                        batch_size=6,
                        save_every_epoch=10,
                        gpu_index=1,
                        resume=True,
                    )
                ],
            )
            panel.close()

    def test_running_state_swaps_start_for_stop_and_locks_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 1, 1)

            stopped: list[bool] = []
            panel.stop_requested.connect(lambda: stopped.append(True))
            panel.set_failure("previous failure")
            panel.set_running(True)
            panel.set_progress(70)
            panel.set_epoch_progress(3, 20)
            panel.set_runtime_status(65, 4)
            panel.stop_button.click()

            self.assertEqual(panel.status_label.text(), "Training")
            self.assertEqual(
                panel.status_label.property("phase"),
                RvcTrainingPhase.TRAIN.value,
            )
            self.assertEqual(panel.stage_label.toolTip(), "")
            self.assertEqual(panel.epoch_label.text(), "3 / 20")
            self.assertEqual(panel.progress_percent_label.text(), "70%")
            self.assertTrue(panel.activity_label.text().startswith("Working"))
            self.assertEqual(
                panel.runtime_label.text(),
                "Elapsed 01:05  |  Last activity 00:04 ago",
            )
            self.assertFalse(panel.runtime_row.isHidden())
            self.assertTrue(panel.start_button.isHidden())
            self.assertFalse(panel.stop_button.isHidden())
            self.assertFalse(panel.target_epoch_spin.isEnabled())
            self.assertEqual(stopped, [True])
            panel.close()

    def test_elapsed_time_formatter_supports_long_training_runs(self) -> None:
        self.assertEqual(format_training_elapsed(5), "00:05")
        self.assertEqual(format_training_elapsed(65), "01:05")
        self.assertEqual(format_training_elapsed(3_661), "01:01:01")


def _record(root: Path, layout: RvcModelPackageLayout) -> RvcModelRecord:
    runtime = root / "runtime"
    return RvcModelRecord(
        model_id="voice",
        name="Voice",
        mode="created",
        runtime_root=runtime,
        source_folder=layout.experiment_dir,
        inference_model=None,
        index_file=None,
        generator_checkpoint=None,
        discriminator_checkpoint=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
