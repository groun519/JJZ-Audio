from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_dataset_analysis_panel import ModelDatasetAnalysisPanel
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.model_dataset_analysis import analyze_model_dataset


class ModelDatasetAnalysisPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_cached_report_is_rendered_and_issue_opens_training_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("voice", (_tone(root / "short.wav"),)).items[0]
            store.select_items("voice", (item.item_id,))
            analyze_model_dataset(store, "voice")
            panel = ModelDatasetAnalysisPanel(store)
            opened: list[str] = []
            panel.edit_requested.connect(opened.append)

            panel.set_model("voice")
            first_issue = panel.issue_list.item(0)
            panel._open_issue(first_issue)

            self.assertNotEqual(panel.duration_value.text(), "-")
            self.assertGreater(panel.issue_list.count(), 0)
            self.assertEqual(opened, [item.item_id])
            self.assertEqual(panel.pitch_value.text(), "A3")
            self.assertAlmostEqual(panel.pitch_chart._center_midi or 0, 57.0, delta=0.2)
            self.assertEqual(len(panel.pitch_chart._coverage_ranges), 1)
            self.assertIn("RVC Pitch", panel.pitch_reference.text())
            panel.close()


def _tone(path: Path) -> Path:
    sample_rate = 16_000
    time = np.arange(round(sample_rate * 0.5), dtype=np.float64) / sample_rate
    audio = 0.2 * np.sin(2 * np.pi * 220 * time)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")
    return path


if __name__ == "__main__":
    unittest.main()
