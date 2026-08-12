from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from jang_app.qt_app.separation_benchmark_review import SeparationBenchmarkReviewWindow


class SeparationBenchmarkReviewWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_builds_blind_candidate_controls_and_saves_rating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review = _review(root)
            window = SeparationBenchmarkReviewWindow(review)
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            self.assertEqual(
                [button.text() for button in window.candidate_group.buttons()],
                ["A · 미평가", "B · 미평가", "C · 미평가"],
            )
            label_text = " ".join(
                label.text() for label in window.centralWidget().findChildren(QLabel)
            )
            self.assertNotIn("HTDemucs", label_text)
            self.assertNotIn("RoFormer", label_text)

            window.issue_groups["vocal_missing"].button(1).click()
            window.decision_groups["vocals"].button(0).click()

            responses = json.loads((root / "responses.json").read_text(encoding="utf-8"))
            self.assertEqual(
                responses["ratings"]["clip:A"]["issues"]["vocal_missing"],
                "some",
            )
            self.assertEqual(
                responses["ratings"]["clip:A"]["decisions"]["vocals"],
                "keep",
            )
            self.assertEqual(window.candidate_group.button(0).text(), "A · 진행 중")
            window.close()

    def test_marks_complete_combination_and_moves_to_next_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = SeparationBenchmarkReviewWindow(_review(Path(temporary)))
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            for group in window.issue_groups.values():
                group.button(0).click()
            window.decision_groups["vocals"].button(0).click()
            window.decision_groups["instrumental"].button(1).click()

            self.assertEqual(window.candidate_group.button(0).text(), "A · 완료")
            window.next_button.click()
            self.assertEqual(window.candidate_group.checkedId(), 1)
            self.assertIn("2 / 3", window.combination_label.text())
            window.close()

    def test_conversion_review_uses_rvc_and_final_mix_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = SeparationBenchmarkReviewWindow(
                _review(Path(temporary), review_type="conversion")
            )
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            self.assertEqual(
                [label for _stage, label in window.stage_specs],
                ["변환 보컬", "최종 믹스", "분리 보컬", "반주", "원곡"],
            )
            self.assertIn("converted_pitch", window.issue_groups)
            self.assertIn("mix_naturalness", window.issue_groups)
            self.assertEqual(
                set(window.decision_groups), {"converted_vocals", "final_mix"}
            )
            for group in window.issue_groups.values():
                group.button(0).click()
            for group in window.decision_groups.values():
                group.button(0).click()
            self.assertEqual(window.candidate_group.button(0).text(), "A · 완료")
            window.close()

    def test_hybrid_review_starts_with_mix_and_keeps_diagnostic_stems_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = SeparationBenchmarkReviewWindow(
                _review(Path(temporary), review_type="hybrid")
            )
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            self.assertEqual(
                [label for _stage, label in window.stage_specs],
                ["최종 믹스", "변환 보컬", "반주", "원곡"],
            )
            self.assertEqual(window._stage, "final_mix")
            self.assertEqual(set(window.decision_groups), {"final_mix"})
            self.assertIn("mix_original_vocal", window.issue_groups)
            self.assertNotIn("converted_pitch", window.issue_groups)
            window.close()


def _review(root: Path, *, review_type: str = "separation") -> Path:
    source = _audio(root / "source.wav")
    candidates = []
    for code in ("A", "B", "C"):
        candidate = {
            "code": code,
            "vocals": str(_audio(root / code / "vocals.wav")),
            "instrumental": str(_audio(root / code / "instrumental.wav")),
        }
        if review_type in {"conversion", "hybrid"}:
            candidate.update(
                {
                    "converted_vocals": str(
                        _audio(root / code / "converted_vocals.wav")
                    ),
                    "final_mix": str(_audio(root / code / "final_mix.wav")),
                }
            )
        candidates.append(candidate)
    path = root / "review.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "review_type": review_type,
                "benchmark_id": "test",
                "title": "Test",
                "responses": str(root / "responses.json"),
                "review_dimensions": ["separation_artifacts"],
                "clips": [
                    {
                        "clip_id": "clip",
                        "title": "Clip",
                        "role": "Artifact test",
                        "source": str(source),
                        "candidates": candidates,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.zeros((44_100, 2), dtype=np.float32)
    sf.write(path, samples, 44_100, subtype="PCM_16")
    return path


if __name__ == "__main__":
    unittest.main()
