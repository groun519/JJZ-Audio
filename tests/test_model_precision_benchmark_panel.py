from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QBoxLayout

from jang_app.qt_app.model_precision_benchmark_panel import (
    ModelPrecisionBenchmarkPanel,
    _format_benchmark_error,
)
from jang_app.services.model_precision_benchmark import (
    ModelPrecisionBenchmark,
    ModelPrecisionBenchmarkPoint,
)
from jang_app.services.rvc_model_workspace import RvcModelRecord


class ModelPrecisionBenchmarkPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_runtime_root_is_explained_cleanly(self) -> None:
        message = _format_benchmark_error(
            "jang_app.services.model_precision_benchmark.ModelPrecisionBenchmarkError: "
            "The selected RVC runtime root does not exist."
        )
        self.assertEqual(message, "선택한 RVC 런타임 폴더를 찾을 수 없습니다.")

    def test_run_button_is_disabled_when_runtime_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inference = root / "voice.pth"
            inference.write_bytes(b"checkpoint")
            missing_runtime = root / "missing-runtime"
            panel = ModelPrecisionBenchmarkPanel(root, missing_runtime)
            panel.set_model(
                RvcModelRecord(
                    model_id="model-1",
                    name="model-1",
                    mode="linked",
                    runtime_root=missing_runtime,
                    source_folder=root,
                    inference_model=inference,
                    index_file=None,
                    generator_checkpoint=None,
                    discriminator_checkpoint=None,
                    created_at="2026-08-13T00:00:00+00:00",
                )
            )
            self.assertFalse(panel.run_button.isEnabled())
            self.assertIn("런타임", panel.status_label.text())
            panel.close()

    def test_run_button_uses_execution_runtime_even_if_record_runtime_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inference = root / "voice.pth"
            inference.write_bytes(b"checkpoint")
            execution_runtime = root / "runtime"
            execution_runtime.mkdir()
            panel = ModelPrecisionBenchmarkPanel(root, execution_runtime)
            panel.set_model(
                RvcModelRecord(
                    model_id="model-1",
                    name="model-1",
                    mode="linked",
                    runtime_root=root / "missing-runtime",
                    source_folder=root,
                    inference_model=inference,
                    index_file=None,
                    generator_checkpoint=None,
                    discriminator_checkpoint=None,
                    created_at="2026-08-13T00:00:00+00:00",
                )
            )
            self.assertTrue(panel.run_button.isEnabled())
            panel.close()

    def test_completed_result_is_presented_as_note_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            panel = ModelPrecisionBenchmarkPanel(root, runtime)
            panel._report = _benchmark_report()

            panel._render()

            self.assertFalse(panel.results_container.isHidden())
            self.assertEqual(panel.recommended_value.text(), "C3 ~ C5")
            self.assertEqual(panel.usable_value.text(), "G2 ~ D5")
            self.assertEqual(panel.stable_value.text(), "25 / 49")
            self.assertIn("C3 ~ C5", panel.headline_label.text())
            self.assertIn("-12 ~ +12", panel.recommended_hint.text())
            self.assertIn("C#5", panel.interpretation_sub.text())
            panel.close()

    def test_empty_result_hides_result_only_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            panel = ModelPrecisionBenchmarkPanel(root, runtime)

            panel._render()

            self.assertTrue(panel.results_container.isHidden())
            self.assertTrue(panel.metrics_container.isHidden())
            self.assertIn("음역", panel.headline_label.text())
            panel.close()

    def test_narrow_layout_stacks_summary_and_result_guide(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            panel = ModelPrecisionBenchmarkPanel(root, runtime)

            panel._apply_responsive_layout(1000)

            self.assertEqual(
                panel.summary_layout.direction(),
                QBoxLayout.Direction.TopToBottom,
            )
            self.assertEqual(
                panel.results_layout.direction(),
                QBoxLayout.Direction.TopToBottom,
            )
            self.assertGreater(panel.info_panel.maximumWidth(), 1000)

            panel._apply_responsive_layout(1400)
            self.assertEqual(
                panel.results_layout.direction(),
                QBoxLayout.Direction.LeftToRight,
            )
            panel.close()


def _benchmark_report() -> ModelPrecisionBenchmark:
    points = tuple(
        ModelPrecisionBenchmarkPoint(
            shift_semitones=shift,
            score=95 if -12 <= shift <= 12 else (70 if -17 <= shift <= 14 else 40),
            status=(
                "stable"
                if -12 <= shift <= 12
                else "caution"
                if -17 <= shift <= 14
                else "avoid"
            ),
            pitch_error=0.1,
            pitch_bias=0.0,
            active_ratio=1.0,
            clipping_ratio=0.0,
            successful_references=3,
            total_references=3,
        )
        for shift in range(-24, 25)
    )
    return ModelPrecisionBenchmark(
        model_id="model-1",
        generated_at="2026-08-20T06:29:24+00:00",
        benchmark_version="precision-v1",
        reference_count=3,
        total_jobs=147,
        successful_jobs=147,
        failed_jobs=0,
        best_shift_semitones=0,
        recommended_low_shift=-12,
        recommended_high_shift=12,
        usable_low_shift=-17,
        usable_high_shift=14,
        stable_point_count=25,
        caution_point_count=7,
        avoid_point_count=17,
        points=points,
        notes=("This score uses the same built-in reference vocal for every model.",),
    )


if __name__ == "__main__":
    unittest.main()
