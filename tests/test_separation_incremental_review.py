from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_incremental_review import build_incremental_review


class IncrementalSeparationReviewTests(unittest.TestCase):
    def test_builds_anonymous_review_and_deduplicates_identical_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = _manifest(
                root / "baseline",
                {
                    "base-vocal": (b"base-vocal", b"base-instrumental"),
                    "base-instrumental": (b"other-vocal", b"approved-instrumental"),
                },
                definition="a" * 64,
            )
            challenger = _manifest(
                root / "challenger",
                {
                    "new-one": (b"new-vocal", b"new-instrumental"),
                    "duplicate": (b"base-vocal", b"new-instrumental"),
                },
                definition="b" * 64,
            )

            review_path, key_path = build_incremental_review(
                challenger,
                baseline,
                baseline_vocal_candidate_id="base-vocal",
                baseline_instrumental_candidate_ids={
                    "clip": "base-instrumental"
                },
                challenger_candidate_ids=("new-one", "duplicate"),
            )

            review = json.loads(review_path.read_text(encoding="utf-8"))
            serialized = json.dumps(review)
            self.assertNotIn("base-vocal", serialized)
            self.assertNotIn("new-one", serialized)
            self.assertNotIn("results", serialized)
            self.assertEqual(
                len(review["clips"][0]["stages"]["vocals"]["candidates"]), 2
            )
            self.assertEqual(
                len(review["clips"][0]["stages"]["instrumental"]["candidates"]),
                2,
            )
            key = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertIn("base-vocal", json.dumps(key))
            self.assertTrue(
                Path(
                    review["clips"][0]["stages"]["vocals"]["candidates"][0][
                        "path"
                    ]
                ).is_file()
            )


def _manifest(
    root: Path,
    candidates: dict[str, tuple[bytes, bytes]],
    *,
    definition: str,
) -> Path:
    source = _write(root / "clips" / "clip.wav", b"source")
    candidate_rows = []
    for candidate_id, (vocal_data, instrumental_data) in candidates.items():
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "label": candidate_id,
                "recipe_id": candidate_id,
            }
        )
        result_root = root / "results" / candidate_id / "clip"
        vocals = _write(result_root / "vocals.wav", vocal_data)
        instrumental = _write(result_root / "no_vocals.wav", instrumental_data)
        (result_root / "benchmark-result.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "definition_sha256": definition,
                    "outputs": {
                        "vocals": _record(vocals),
                        "instrumental": _record(instrumental),
                    },
                }
            ),
            encoding="utf-8",
        )
    manifest = root / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "benchmark_id": root.name,
                "title": root.name,
                "definition_sha256": definition,
                "root": str(root),
                "clips": [
                    {
                        "clip_id": "clip",
                        "title": "Clip",
                        "role": "Test",
                        "path": str(source),
                        "sha256": file_sha256(source),
                    }
                ],
                "candidates": candidate_rows,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "size": path.stat().st_size,
    }


if __name__ == "__main__":
    unittest.main()
