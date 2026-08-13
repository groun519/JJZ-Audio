from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_precision_benchmark_panel import (
    ModelPrecisionBenchmarkPanel,
    _format_benchmark_error,
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


if __name__ == "__main__":
    unittest.main()
