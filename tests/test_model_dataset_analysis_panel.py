from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.model_dataset_analysis_panel import (
    DatasetIssueRow,
    ModelDatasetAnalysisPanel,
)
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.model_dataset_analysis import DatasetAnalysisIssue, analyze_model_dataset


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

    def test_issue_rows_are_parented_before_size_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = ModelDatasetAnalysisPanel(ModelDatasetStore(Path(temporary)))
            original_size_hint = DatasetIssueRow.sizeHint
            measured_as_window: list[bool] = []

            def checked_size_hint(row: DatasetIssueRow):
                measured_as_window.append(row.isWindow())
                return original_size_hint(row)

            issue = DatasetAnalysisIssue(
                "noise",
                "attention",
                "Review this material.",
                item_id="item-1",
            )
            with patch.object(
                DatasetIssueRow,
                "sizeHint",
                checked_size_hint,
            ):
                panel._populate_issues((issue,))

            self.assertTrue(measured_as_window)
            self.assertFalse(any(measured_as_window))
            row = panel.issue_list.itemWidget(panel.issue_list.item(0))
            self.assertIs(row.parentWidget(), panel.issue_list.viewport())
            panel.close()

    def test_issue_details_never_show_as_temporary_top_level_windows(self) -> None:
        shown_as_window: list[QWidget] = []

        class WindowShowProbe(QObject):
            def eventFilter(self, watched, event):  # noqa: N802
                if (
                    event.type() == QEvent.Type.Show
                    and isinstance(watched, QWidget)
                    and watched.objectName() == "DatasetAnalysisMeta"
                    and watched.isWindow()
                ):
                    shown_as_window.append(watched)
                return False

        probe = WindowShowProbe()
        self.app.installEventFilter(probe)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                panel = ModelDatasetAnalysisPanel(ModelDatasetStore(Path(temporary)))
                panel._populate_issues(
                    (
                        DatasetAnalysisIssue(
                            "noise",
                            "attention",
                            "Review this material.",
                            item_id="item-1",
                            source_name="voice.wav",
                            start_ms=1000,
                            end_ms=2000,
                        ),
                    )
                )
                self.app.processEvents()

                self.assertEqual(shown_as_window, [])
                panel.close()
        finally:
            self.app.removeEventFilter(probe)


def _tone(path: Path) -> Path:
    sample_rate = 16_000
    time = np.arange(round(sample_rate * 0.5), dtype=np.float64) / sample_rate
    audio = 0.2 * np.sin(2 * np.pi * 220 * time)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")
    return path


if __name__ == "__main__":
    unittest.main()
