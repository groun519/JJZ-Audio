from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.separation_benchmark_analysis import (
    analyze_conversion_review,
    analyze_hybrid_review,
    analyze_separation_review,
)
from jang_app.services.separation_benchmark_review import SeparationBenchmarkReviewError


class SeparationBenchmarkAnalysisTests(unittest.TestCase):
    def test_resolves_blind_winner_and_recommends_hybrid_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write_json(
                root / "blind-key.json",
                {
                    "benchmark_id": "test",
                    "clips": [
                        {
                            "clip_id": "clip",
                            "candidates": [
                                _identity("A", "model-a", "Model A"),
                                _identity("B", "model-b", "Model B"),
                            ],
                        }
                    ],
                },
            )
            responses = _write_json(
                root / "blind-review-responses.json",
                {
                    "ratings": {
                        "clip:A": _rating("keep", "reject", vocal_issue=0, inst_issue=2),
                        "clip:B": _rating("repair", "keep", vocal_issue=1, inst_issue=0),
                    },
                    "winners": {"clip": "B"},
                },
            )

            json_path, markdown_path = analyze_separation_review(key, responses)

            analysis = json.loads(json_path.read_text(encoding="utf-8"))
            clip = analysis["clip_results"][0]
            self.assertEqual(clip["selected_winner"]["candidate_id"], "model-b")
            self.assertEqual(
                clip["stem_recommendations"]["vocals"]["candidate_id"], "model-a"
            )
            self.assertEqual(
                clip["stem_recommendations"]["instrumental"]["candidate_id"], "model-b"
            )
            self.assertTrue(clip["hybrid_recommended"])
            self.assertIn("Model A", markdown_path.read_text(encoding="utf-8"))

    def test_rejects_incomplete_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write_json(
                root / "blind-key.json",
                {
                    "clips": [
                        {
                            "clip_id": "clip",
                            "candidates": [_identity("A", "model-a", "Model A")],
                        }
                    ]
                },
            )
            responses = _write_json(
                root / "blind-review-responses.json",
                {"ratings": {}, "winners": {}},
            )

            with self.assertRaisesRegex(SeparationBenchmarkReviewError, "incomplete"):
                analyze_separation_review(key, responses)

    def test_analyzes_conversion_review_and_preserves_reviewer_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write_json(
                root / "conversion-key.json",
                {
                    "benchmark_id": "test",
                    "clips": [
                        {
                            "clip_id": "clip",
                            "candidates": [
                                _identity("A", "model-a", "Model A"),
                                _identity("B", "model-b", "Model B"),
                            ],
                        }
                    ],
                },
            )
            responses = _write_json(
                root / "conversion-review-responses.json",
                {
                    "ratings": {
                        "clip:A": _conversion_rating(
                            "keep", "repair", converted_issue=0, mix_issue=1
                        ),
                        "clip:B": _conversion_rating(
                            "repair", "keep", converted_issue=1, mix_issue=0
                        ),
                    },
                    "winners": {"clip": "A"},
                },
            )

            json_path, markdown_path = analyze_conversion_review(key, responses)

            analysis = json.loads(json_path.read_text(encoding="utf-8"))
            clip = analysis["clip_results"][0]
            self.assertEqual(analysis["review_type"], "conversion")
            self.assertEqual(
                clip["stem_recommendations"]["converted_vocals"]["candidate_id"],
                "model-a",
            )
            self.assertEqual(
                clip["stem_recommendations"]["final_mix"]["candidate_id"],
                "model-b",
            )
            report = markdown_path.read_text(encoding="utf-8")
            self.assertIn("Blind Conversion Review Analysis", report)
            self.assertIn("Reviewer Notes", report)
            self.assertIn("Model A", report)
            self.assertIn("voice was stable", report)

    def test_analyzes_final_mix_only_hybrid_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write_json(
                root / "hybrid-key.json",
                {
                    "benchmark_id": "test",
                    "clips": [
                        {
                            "clip_id": "clip",
                            "candidates": [
                                _identity("A", "incumbent", "Current pairing"),
                                _identity("B", "hybrid", "Hybrid pairing"),
                            ],
                        }
                    ],
                },
            )
            responses = _write_json(
                root / "hybrid-review-responses.json",
                {
                    "ratings": {
                        "clip:A": _hybrid_rating("keep", issue=0),
                        "clip:B": _hybrid_rating("keep", issue=0),
                    },
                    "winners": {"clip": "B"},
                },
            )

            json_path, markdown_path = analyze_hybrid_review(key, responses)

            analysis = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(analysis["review_type"], "hybrid")
            self.assertEqual(
                analysis["clip_results"][0]["selected_winner"]["candidate_id"],
                "hybrid",
            )
            self.assertEqual(
                analysis["clip_results"][0]["stem_recommendations"]["final_mix"][
                    "candidate_id"
                ],
                "hybrid",
            )
            self.assertFalse(analysis["clip_results"][0]["hybrid_recommended"])
            self.assertIn(
                "Blind Hybrid Review Analysis",
                markdown_path.read_text(encoding="utf-8"),
            )


def _identity(code: str, candidate_id: str, label: str) -> dict[str, str]:
    return {
        "code": code,
        "candidate_id": candidate_id,
        "candidate_label": label,
        "recipe_id": f"recipe-{candidate_id}",
    }


def _rating(
    vocal_decision: str,
    instrumental_decision: str,
    *,
    vocal_issue: int,
    inst_issue: int,
) -> dict[str, object]:
    levels = ("none", "some", "severe")
    return {
        "issues": {
            "vocal_missing": levels[vocal_issue],
            "vocal_unwanted_sound": "none",
            "vocal_effect_residue": "none",
            "vocal_damage": "none",
            "instrumental_vocal_residue": levels[inst_issue],
            "instrumental_effect_residue": "none",
            "instrumental_damage": "none",
            "instrumental_artifacts": "none",
        },
        "decisions": {
            "vocals": vocal_decision,
            "instrumental": instrumental_decision,
        },
    }


def _conversion_rating(
    converted_decision: str,
    mix_decision: str,
    *,
    converted_issue: int,
    mix_issue: int,
) -> dict[str, object]:
    levels = ("none", "some", "severe")
    return {
        "issues": {
            "converted_missing": levels[converted_issue],
            "converted_pitch": "none",
            "converted_timbre": "none",
            "converted_artifacts": "none",
            "mix_original_vocal": levels[mix_issue],
            "mix_vocal_clarity": "none",
            "mix_balance": "none",
            "mix_naturalness": "none",
        },
        "decisions": {
            "converted_vocals": converted_decision,
            "final_mix": mix_decision,
        },
        "notes": "voice was stable",
    }


def _hybrid_rating(decision: str, *, issue: int) -> dict[str, object]:
    levels = ("none", "some", "severe")
    return {
        "issues": {
            "mix_original_vocal": levels[issue],
            "mix_vocal_clarity": "none",
            "mix_balance": "none",
            "mix_naturalness": "none",
        },
        "decisions": {"final_mix": decision},
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
