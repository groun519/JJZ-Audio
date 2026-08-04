from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_training_panel import ModelTrainingPanel
from jang_app.services.i18n import LANGUAGE_ENGLISH, set_language
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.rvc_training_state import RvcTrainingStateStore
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
            panel.set_running(True)
            panel.stop_button.click()

            self.assertTrue(panel.start_button.isHidden())
            self.assertFalse(panel.stop_button.isHidden())
            self.assertFalse(panel.target_epoch_spin.isEnabled())
            self.assertEqual(stopped, [True])
            panel.close()


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
