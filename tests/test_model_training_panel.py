from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_training_panel import ModelTrainingPanel, format_training_elapsed
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from jang_app.services.rvc_training_presets import RvcTrainingPresetId
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
            self.assertFalse(panel.mode_control.isHidden())
            self.assertTrue(panel.resume_mode_button.isChecked())
            self.assertEqual(panel.checkpoint_value.text(), "Step 120")
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

    def test_start_over_mode_resets_epoch_and_disables_resume_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            (layout.experiment_dir / "G_120.pth").write_bytes(b"generator")
            (layout.experiment_dir / "D_120.pth").write_bytes(b"discriminator")
            state = RvcTrainingStateStore("voice", layout).refresh_checkpoint_pair()
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 2, 2, 65_000)

            emitted: list[RvcTrainingRunSettings] = []
            panel.start_requested.connect(emitted.append)
            panel.fresh_mode_button.click()
            panel.target_epoch_spin.setValue(20)
            panel.start_button.click()

            self.assertEqual(panel.epoch_label.text(), "0 / 20")
            self.assertEqual(panel.start_button.text(), "Start Training")
            self.assertFalse(emitted[0].resume)
            self.assertEqual(panel.duration_value.text(), "01:05")
            panel.close()

    def test_training_requires_every_selected_material_to_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            record = _record(root, layout)

            panel.set_model(record, state, 1, 2)
            self.assertFalse(panel.start_button.isEnabled())
            self.assertEqual(panel.readiness_badge.property("readiness"), "blocked")
            self.assertFalse(panel.start_hint_label.isHidden())

            panel.set_model(record, state, 2, 2)
            self.assertTrue(panel.start_button.isEnabled())
            self.assertEqual(panel.readiness_badge.property("readiness"), "review")
            self.assertTrue(panel.start_hint_label.isHidden())
            panel.close()

    def test_preflight_rows_keep_title_and_wrapped_detail_visible(self) -> None:
        panel = ModelTrainingPanel()
        panel.resize(1100, 500)
        panel.show()
        self.app.processEvents()

        for frame, title, detail in panel.preflight_rows.values():
            with self.subTest(title=title.text()):
                self.assertTrue(detail.wordWrap())
                self.assertGreaterEqual(frame.height(), frame.minimumHeight())
                self.assertGreaterEqual(detail.height(), detail.minimumHeight())
                self.assertLessEqual(
                    detail.geometry().bottom(),
                    frame.contentsRect().bottom(),
                )
        panel.close()

    def test_presets_apply_settings_and_manual_edits_switch_to_custom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 1, 1)

            panel.preset_buttons[RvcTrainingPresetId.STANDARD].click()

            self.assertEqual(panel.target_epoch_spin.value(), 200)
            self.assertEqual(panel.batch_size_spin.value(), 4)
            self.assertEqual(panel.save_interval_spin.value(), 20)
            self.assertIn("Balanced training", panel.preset_summary_label.text())

            panel.target_epoch_spin.setValue(210)

            self.assertTrue(
                panel.preset_buttons[RvcTrainingPresetId.CUSTOM].isChecked()
            )
            self.assertIn("Manual training settings", panel.preset_summary_label.text())
            panel.close()

    def test_cpu_preset_and_info_popovers_explain_current_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            panel.set_compute_backends(RvcComputeBackend.DIRECTML, RvcComputeBackend.CPU)
            panel.set_model(_record(root, layout), state, 1, 1)

            panel.preset_buttons[RvcTrainingPresetId.HIGH_QUALITY].click()

            self.assertEqual(panel.batch_size_spin.value(), 2)
            self.assertIn("Current recommendation: 2", panel.batch_size_info.toolTip())
            self.assertIn("CPU mode", panel.training_device_info.toolTip())

            set_language(LANGUAGE_KOREAN)
            panel.apply_language()

            self.assertEqual(
                panel.preset_buttons[RvcTrainingPresetId.HIGH_QUALITY].text(),
                "고품질",
            )
            self.assertIn("현재 권장값: 2", panel.batch_size_info.toolTip())
            panel.close()

    def test_low_memory_gpu_applies_environment_based_batch_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            panel.set_compute_backends(
                RvcComputeBackend.CUDA,
                RvcComputeBackend.CUDA,
                adapter_name="NVIDIA GeForce GTX 1650",
                adapter_memory_bytes=4 * 1024**3,
            )
            panel.set_model(_record(root, layout), state, 1, 1)

            panel.preset_buttons[RvcTrainingPresetId.STANDARD].click()

            self.assertEqual(panel.batch_size_spin.value(), 2)
            self.assertIn("GTX 1650", panel.preset_summary_label.text())
            self.assertIn("4.0 GB VRAM", panel.batch_size_info.toolTip())
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
            panel.set_stage("Training Model")
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
            self.assertEqual(panel.workflow_progress.stage_state("train"), "active")
            self.assertEqual(
                panel.workflow_progress.stage_state("features"),
                "complete",
            )
            self.assertTrue(panel.activity_label.text().startswith("Working"))
            self.assertEqual(
                panel.runtime_label.text(),
                "Elapsed 01:05  |  Last activity 00:04 ago",
            )
            self.assertEqual(panel.remaining_label.text(), "Estimating remaining time")
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

    def test_estimates_remaining_time_after_epoch_timing_is_available(self) -> None:
        panel = ModelTrainingPanel()
        panel.set_running(True)

        with patch(
            "jang_app.qt_app.model_training_panel.monotonic",
            side_effect=(100.0, 110.0),
        ):
            panel.set_epoch_progress(1, 20)
            panel.set_epoch_progress(2, 20)
        panel.set_runtime_status(30, 0)

        self.assertEqual(panel.remaining_label.text(), "About 03:00 remaining")
        panel.close()

    def test_directml_inference_uses_an_explicit_cpu_training_device(self) -> None:
        panel = ModelTrainingPanel()

        panel.set_compute_backends(RvcComputeBackend.DIRECTML, RvcComputeBackend.CPU)

        self.assertEqual(panel.device_stack.currentWidget(), panel.cpu_device_label)
        self.assertEqual(panel.cpu_device_label.text(), "CPU")
        self.assertIn("DirectML / CPU Training", panel.profile_label.text())
        panel.close()

    def test_complete_state_marks_every_workflow_stage_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            store = RvcTrainingStateStore("voice", layout)
            state = store.save(
                replace(
                    store.load(),
                    phase=RvcTrainingPhase.COMPLETE,
                    current_epoch=20,
                    target_epoch=20,
                )
            )
            panel = ModelTrainingPanel()

            panel.set_model(_record(root, layout), state, 1, 1)

            self.assertEqual(panel.progress_bar.value(), 100)
            self.assertTrue(
                all(
                    panel.workflow_progress.stage_state(key) == "complete"
                    for key in ("data", "prepare", "features", "train", "index")
                )
            )
            panel.close()

    def test_cuda_memory_recovery_retries_with_a_smaller_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            state = RvcTrainingStateStore("voice", layout).initialize()
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 1, 1)
            panel.batch_size_spin.setValue(6)
            emitted: list[RvcTrainingRunSettings] = []
            panel.start_requested.connect(emitted.append)

            panel.set_failure(
                "RuntimeError: CUDA out of memory",
                task_id="task-oom",
                diagnostic_code="CUDA_OUT_OF_MEMORY",
            )
            panel.recovery_primary_button.click()

            self.assertFalse(panel.recovery_card.isHidden())
            self.assertTrue(panel.start_button.isHidden())
            self.assertEqual(panel.recovery_code_label.text(), "CUDA_OUT_OF_MEMORY")
            self.assertEqual(panel.batch_size_spin.value(), 3)
            self.assertEqual(emitted[0].batch_size, 3)
            panel.close()

    def test_failed_checkpoint_offers_resume_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "Voice")
            layout.create()
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            state = RvcTrainingStateStore("voice", layout).record_failure_context(
                "Unexpected trainer failure",
                task_id="task-resume",
                diagnostic_code="UNEXPECTED_ERROR",
            )
            panel = ModelTrainingPanel()
            panel.set_model(_record(root, layout), state, 1, 1)
            emitted: list[RvcTrainingRunSettings] = []
            diagnostics: list[str] = []
            panel.start_requested.connect(emitted.append)
            panel.diagnostics_requested.connect(diagnostics.append)

            panel.recovery_diagnostics_button.click()
            panel.recovery_primary_button.click()

            self.assertEqual(
                panel.recovery_primary_button.text(),
                "Resume from Checkpoint",
            )
            self.assertEqual(diagnostics, ["task-resume"])
            self.assertTrue(emitted[0].resume)
            panel.close()

    def test_runtime_recovery_opens_system_setup(self) -> None:
        panel = ModelTrainingPanel()
        requested: list[bool] = []
        panel.system_setup_requested.connect(lambda: requested.append(True))

        panel.set_failure(
            "ModuleNotFoundError: No module named 'torch'",
            diagnostic_code="PYTHON_MODULE_MISSING",
        )
        panel.recovery_primary_button.click()

        self.assertEqual(panel.recovery_primary_button.text(), "Open System Setup")
        self.assertEqual(requested, [True])
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
