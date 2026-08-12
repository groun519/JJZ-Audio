from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.separation_incremental_analysis import (
    analyze_incremental_review,
)
from jang_app.services.separation_incremental_review import (
    IncrementalSeparationReviewError,
)


class IncrementalSeparationAnalysisTests(unittest.TestCase):
    def test_advances_only_candidates_marked_better(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write_json(root / "key.json", _key())
            responses = _write_json(
                root / "responses.json",
                {
                    "schema": 1,
                    "comparisons": {
                        "clip:vocals:B": "better",
                        "clip:vocals:C": "same",
                        "clip:instrumental:B": "worse",
                        "clip:instrumental:C": "same",
                    },
                    "notes": {"clip:vocals": "clearer"},
                },
            )

            analysis_path, report_path = analyze_incremental_review(
                key, responses
            )

            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            stages = analysis["clip_results"][0]["stages"]
            self.assertEqual(
                stages["vocals"]["selected_candidate_id"], "new-b"
            )
            self.assertEqual(
                stages["instrumental"]["selected_candidate_id"], "base-inst"
            )
            self.assertEqual(stages["vocals"]["note"], "clearer")
            self.assertIn("new-b", report_path.read_text(encoding="utf-8"))

    def test_rejects_incomplete_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(
                IncrementalSeparationReviewError, "4 decisions missing"
            ):
                analyze_incremental_review(
                    _write_json(root / "key.json", _key()),
                    _write_json(
                        root / "responses.json",
                        {"schema": 1, "comparisons": {}, "notes": {}},
                    ),
                )


def _key() -> dict[str, object]:
    return {
        "schema": 1,
        "review_type": "incremental-separation",
        "benchmark_id": "benchmark",
        "clips": [
            {
                "clip_id": "clip",
                "stages": {
                    "vocals": {
                        "candidates": [
                            _candidate("A", "base-vocal", "reference"),
                            _candidate("B", "new-b", "challenger"),
                            _candidate("C", "new-c", "challenger"),
                        ]
                    },
                    "instrumental": {
                        "candidates": [
                            _candidate("A", "base-inst", "reference"),
                            _candidate("B", "new-b", "challenger"),
                            _candidate("C", "new-c", "challenger"),
                        ]
                    },
                },
            }
        ],
    }


def _candidate(code: str, candidate_id: str, role: str) -> dict[str, str]:
    return {
        "code": code,
        "candidate_id": candidate_id,
        "candidate_label": candidate_id,
        "role": role,
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
