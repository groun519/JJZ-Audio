from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from jang_app.qt_app.model_dataset_analysis_panel import (
    DatasetIssueRow,
    ModelDatasetAnalysisPanel,
)
from jang_app.services.i18n import tr
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
            opened: list[tuple[str, str, int, int]] = []
            panel.edit_requested.connect(lambda *values: opened.append(values))

            panel.set_model("voice")
            first_issue = panel.issue_list.item(0)
            panel._open_issue(first_issue)

            self.assertNotEqual(panel.duration_value.text(), "-")
            self.assertGreater(panel.issue_list.count(), 0)
            self.assertEqual(opened, [(item.item_id, "", 0, 500)])
            self.assertEqual(panel.pitch_value.text(), "A3")
            self.assertAlmostEqual(panel.pitch_chart._center_midi or 0, 57.0, delta=0.2)
            self.assertEqual(len(panel.pitch_chart._coverage_ranges), 1)
            self.assertIn("RVC Pitch", panel.pitch_reference.text())
            panel.close()

    def test_issue_navigation_preserves_the_exact_clip_and_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = ModelDatasetAnalysisPanel(ModelDatasetStore(Path(temporary)))
            opened: list[tuple[str, str, int, int]] = []
            panel.edit_requested.connect(lambda *values: opened.append(values))
            panel._populate_issues(
                (
                    DatasetAnalysisIssue(
                        "clip_too_short",
                        "attention",
                        "This clip is shorter than 1 second.",
                        item_id="item-1",
                        clip_id="clip-16",
                        start_ms=41_200,
                        end_ms=41_850,
                    ),
                )
            )

            panel._open_issue(panel.issue_list.item(0))

            self.assertEqual(opened, [("item-1", "clip-16", 41_200, 41_850)])
            panel.close()

    def test_quality_findings_use_attention_and_info_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = ModelDatasetAnalysisPanel(ModelDatasetStore(Path(temporary)))
            panel._populate_issues(
                (
                    DatasetAnalysisIssue(
                        "clip_too_short",
                        "attention",
                        "This clip is shorter than 1 second.",
                        item_id="item-1",
                        clip_id="clip-1",
                    ),
                    DatasetAnalysisIssue(
                        "clip_too_long",
                        "info",
                        "This clip is longer than 15 seconds.",
                        item_id="item-1",
                        clip_id="clip-2",
                    ),
                )
            )

            badges = tuple(
                panel.issue_list.itemWidget(panel.issue_list.item(index)).findChild(
                    QLabel,
                    "DatasetIssueBadge",
                )
                for index in range(panel.issue_list.count())
            )
            self.assertEqual(
                tuple(badge.text() for badge in badges),
                (tr("Attention"), tr("Info")),
            )
            self.assertEqual(
                tuple(badge.property("severity") for badge in badges),
                ("attention", "info"),
            )
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
