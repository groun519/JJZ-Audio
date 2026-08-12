from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_benchmark_review import (
    build_blind_review,
    build_conversion_review,
    build_hybrid_review,
    load_review_responses,
    save_review_responses,
)


class SeparationBenchmarkReviewTests(unittest.TestCase):
    def test_builds_stable_blind_pack_and_separate_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _benchmark(root)

            review_path, key_path = build_blind_review(manifest)
            first_review = json.loads(review_path.read_text(encoding="utf-8"))
            first_key = json.loads(key_path.read_text(encoding="utf-8"))
            build_blind_review(manifest)
            second_review = json.loads(review_path.read_text(encoding="utf-8"))
            key = json.loads(key_path.read_text(encoding="utf-8"))

            self.assertEqual(
                [item["code"] for item in second_review["clips"][0]["candidates"]],
                ["A", "B", "C"],
            )
            self.assertNotIn("candidate_id", json.dumps(first_review))
            self.assertNotIn("candidate_id", json.dumps(second_review))
            self.assertEqual(
                [item["candidate_id"] for item in first_key["clips"][0]["candidates"]],
                [item["candidate_id"] for item in key["clips"][0]["candidates"]],
            )

    def test_response_store_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "responses.json"
            responses = load_review_responses(target)
            responses["ratings"] = {"clip:A": {"decision": "keep"}}

            save_review_responses(target, responses)

            loaded = load_review_responses(target)
            self.assertEqual(loaded["ratings"]["clip:A"]["decision"], "keep")

    def test_builds_conversion_review_from_verified_downstream_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _benchmark(root)
            benchmark = json.loads(manifest.read_text(encoding="utf-8"))
            for candidate in benchmark["candidates"]:
                for clip in benchmark["clips"]:
                    result_root = (
                        root / "results" / candidate["candidate_id"] / clip["clip_id"]
                    )
                    converted = _write(
                        result_root / "downstream" / "converted.wav", b"converted"
                    )
                    final_mix = _write(
                        result_root / "downstream" / "final_mix.wav", b"mix"
                    )
                    (result_root / "downstream" / "benchmark-render.json").write_text(
                        json.dumps(
                            {
                                "status": "completed",
                                "definition_sha256": "a" * 64,
                                "outputs": {
                                    "converted_vocals": _record(converted),
                                    "final_mix": _record(final_mix),
                                },
                            }
                        ),
                        encoding="utf-8",
                    )

            review_path, key_path = build_conversion_review(manifest)

            review = json.loads(review_path.read_text(encoding="utf-8"))
            key = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertEqual(review["review_type"], "conversion")
            self.assertIn("converted_vocals", review["clips"][0]["candidates"][0])
            self.assertIn("final_mix", review["clips"][0]["candidates"][0])
            self.assertNotIn("candidate_id", json.dumps(review))
            self.assertEqual(key["review_type"], "conversion")

    def test_builds_hybrid_review_with_hidden_pair_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _write(root / "source.wav", b"source")
            candidates = []
            for candidate_id in ("incumbent", "recommended-hybrid"):
                converted = _write(root / candidate_id / "converted.wav", b"converted")
                instrumental = _write(
                    root / candidate_id / "instrumental.wav", candidate_id.encode()
                )
                final_mix = _write(root / candidate_id / "final.wav", b"mix")
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "label": candidate_id,
                        "vocal_candidate_id": "kim",
                        "instrumental_candidate_id": "kim" if candidate_id == "incumbent" else "ht",
                        "converted_vocals": _record(converted),
                        "instrumental": _record(instrumental),
                        "final_mix": _record(final_mix),
                    }
                )
            manifest = root / "hybrid-benchmark.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "status": "completed",
                        "benchmark_id": "test",
                        "root": str(root),
                        "plan_sha256": "b" * 64,
                        "clips": [
                            {
                                "clip_id": "clip",
                                "source": _record(source),
                                "candidates": candidates,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            review_path, key_path = build_hybrid_review(manifest)

            review = json.loads(review_path.read_text(encoding="utf-8"))
            key = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertEqual(review["review_type"], "hybrid")
            self.assertNotIn("candidate_id", json.dumps(review))
            self.assertNotIn("recommended-hybrid", json.dumps(review))
            self.assertIn("final_mix", review["clips"][0]["candidates"][0])
            self.assertIn("converted_vocals", review["clips"][0]["candidates"][0])
            self.assertEqual(key["review_type"], "hybrid")
            self.assertIn("instrumental_candidate_id", key["clips"][0]["candidates"][0])


def _benchmark(root: Path) -> Path:
    clips = []
    candidates = []
    for candidate_id in ("one", "two", "three"):
        candidates.append(
            {
                "candidate_id": candidate_id,
                "label": candidate_id.title(),
                "recipe_id": f"recipe-{candidate_id}",
            }
        )
    for clip_id in ("clip-one", "clip-two"):
        source = _write(root / "clips" / f"{clip_id}.wav", clip_id.encode())
        clips.append(
            {
                "clip_id": clip_id,
                "title": clip_id.title(),
                "role": "Test role",
                "path": str(source),
            }
        )
        for candidate in candidates:
            output = root / "results" / candidate["candidate_id"] / clip_id
            vocals = _write(output / "vocals.wav", b"vocals")
            instrumental = _write(output / "no_vocals.wav", b"instrumental")
            (output / "benchmark-result.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "definition_sha256": "a" * 64,
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
                "benchmark_id": "test",
                "title": "Test",
                "definition_sha256": "a" * 64,
                "root": str(root),
                "review_dimensions": ["artifacts"],
                "clips": clips,
                "candidates": candidates,
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
    return {"path": str(path), "sha256": file_sha256(path), "size": path.stat().st_size}


if __name__ == "__main__":
    unittest.main()
