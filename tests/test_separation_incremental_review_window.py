from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.separation_incremental_review import (
    IncrementalSeparationReviewWindow,
)


class IncrementalSeparationReviewWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_saves_relative_decision_without_rating_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = IncrementalSeparationReviewWindow(_review(root))
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            self.assertEqual(
                [button.text() for button in window.candidate_group.buttons()],
                ["A · 기준", "B · 신규", "C · 신규"],
            )
            self.assertFalse(window.evaluation.isHidden())
            window.candidate_group.button(1).click()
            window.comparison_groups[0].button(0).click()

            responses = json.loads(
                (root / "responses.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                responses["comparisons"]["clip:vocals:B"], "better"
            )
            self.assertNotIn("clip:vocals:A", responses["comparisons"])
            self.assertIn("판단 1 / 8", window.progress_label.text())

            window.stage_group.button(1).click()
            self.assertEqual(window._stage, "instrumental")
            self.assertEqual(window.comparison_groups[0].checkedId(), -1)
            window.stage_group.button(2).click()
            self.assertEqual(window._stage, "source")
            self.assertTrue(window.evaluation.isHidden())
            self.assertEqual(window.candidate_group.button(0).text(), "원곡")
            window.close()

    def test_followup_hides_unavailable_stage_and_uses_dynamic_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review = json.loads(_review(root).read_text(encoding="utf-8"))
            review["review_type"] = "incremental-followup"
            review["title"] = "승자 조합 최종 검수"
            review["stage_definitions"] = [
                {
                    "key": "converted_vocals",
                    "label": "변환 보컬",
                    "criteria": "변환 품질",
                },
                {
                    "key": "final_mix",
                    "label": "최종 믹스",
                    "criteria": "믹스 품질",
                },
            ]
            for clip in review["clips"]:
                clip["stages"] = {
                    "final_mix": clip["stages"]["vocals"]
                }
            path = root / "followup.json"
            path.write_text(json.dumps(review), encoding="utf-8")

            window = IncrementalSeparationReviewWindow(path)
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            self.assertEqual(window._stage, "final_mix")
            self.assertTrue(window.stage_group.button(0).isHidden())
            self.assertEqual(window.stage_group.button(1).text(), "최종 믹스")
            self.assertEqual(window.candidate_group.button(1).text(), "B · 도전자")
            window.close()


def _review(root: Path) -> Path:
    source = _audio(root / "source.wav")
    clips = []
    for clip_id in ("clip", "clip-two"):
        stages = {}
        for stage in ("vocals", "instrumental"):
            stages[stage] = {
                "candidates": [
                    {
                        "code": code,
                        "path": str(_audio(root / clip_id / stage / f"{code}.wav")),
                    }
                    for code in ("A", "B", "C")
                ]
            }
        clips.append(
            {
                "clip_id": clip_id,
                "title": clip_id,
                "role": "Test role",
                "source": str(source),
                "stages": stages,
            }
        )
    path = root / "review.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "review_type": "incremental-separation",
                "benchmark_id": "test",
                "title": "Test",
                "responses": str(root / "responses.json"),
                "clips": clips,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros((4_410, 2), dtype=np.float32), 44_100)
    return path


if __name__ == "__main__":
    unittest.main()
