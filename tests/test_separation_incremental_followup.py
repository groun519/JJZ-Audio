from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_incremental_followup import (
    build_incremental_followup,
)


class IncrementalSeparationFollowupTests(unittest.TestCase):
    def test_renders_only_advancing_combination_from_existing_conversions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = _manifest(root / "baseline", "baseline", (0.1, 0.2))
            challenger = _manifest(root / "challenger", "new", (0.3, 0.4))
            analysis = root / "analysis.json"
            analysis.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "complete": True,
                        "benchmark_id": "challenger",
                        "clip_results": [
                            {
                                "clip_id": "clip",
                                "stages": {
                                    "vocals": _stage("baseline", "new"),
                                    "instrumental": _stage("baseline", "new"),
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result_path, review_path, key_path = build_incremental_followup(
                challenger, baseline, analysis
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(len(result["clips"]), 1)
            self.assertTrue(
                Path(result["clips"][0]["challenger"]["final_mix"]["path"]).is_file()
            )
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(review["review_type"], "incremental-followup")
            self.assertEqual(
                set(review["clips"][0]["stages"]),
                {"converted_vocals", "final_mix"},
            )
            key = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertEqual(
                key["clips"][0]["candidates"][1]["vocal_candidate_id"],
                "new",
            )


def _stage(reference: str, advancing: str) -> dict[str, object]:
    return {
        "reference": {"candidate_id": reference},
        "advancing": [{"candidate_id": advancing}],
    }


def _manifest(root: Path, candidate_id: str, values: tuple[float, float]) -> Path:
    definition = candidate_id * 8
    source = _audio(root / "clips" / "clip.wav", 0.5)
    result_root = root / "results" / candidate_id / "clip"
    vocals = _audio(result_root / "vocals.wav", values[0])
    instrumental = _audio(result_root / "no_vocals.wav", values[1])
    converted = _audio(result_root / "downstream" / "converted.wav", values[0])
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
    (result_root / "downstream" / "benchmark-render.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "definition_sha256": definition,
                "outputs": {"converted_vocals": _record(converted)},
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
                "definition_sha256": definition,
                "root": str(root),
                "clips": [
                    {
                        "clip_id": "clip",
                        "title": "Clip",
                        "path": str(source),
                        "sha256": file_sha256(source),
                    }
                ],
                "candidates": [{"candidate_id": candidate_id}],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _audio(path: Path, value: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.full((441, 2), value, dtype=np.float32), 44_100)
    return path


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "size": path.stat().st_size,
    }


if __name__ == "__main__":
    unittest.main()
