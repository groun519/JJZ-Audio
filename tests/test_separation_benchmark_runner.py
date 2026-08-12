from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.pipeline.separation_engine import SeparationResult
from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_benchmark_runner import run_prepared_benchmark
from jang_app.services.separation_recipe import SeparationRecipe


class SeparationBenchmarkRunnerTests(unittest.TestCase):
    def test_runs_candidate_first_and_resumes_verified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clips = root / "clips"
            first = _write(clips / "first.wav", b"first")
            second = _write(clips / "second.wav", b"second")
            manifest = _write_manifest(root, first, second)
            calls: list[tuple[str, str]] = []

            def separate(
                source: Path,
                output: Path,
                recipe: SeparationRecipe,
                progress,
            ) -> SeparationResult:
                calls.append((recipe.recipe_id, source.stem))
                if progress is not None:
                    progress(50)
                vocals = _write(output / "vocals.wav", b"vocals-" + source.read_bytes())
                instrumental = _write(output / "no_vocals.wav", b"music-" + source.read_bytes())
                return SeparationResult(source, output, vocals, instrumental, recipe)

            progress = run_prepared_benchmark(manifest, separator=separate)

            self.assertEqual(
                calls,
                [
                    ("demucs-standard-v1", "first"),
                    ("demucs-standard-v1", "second"),
                    ("roformer-precision-v1", "first"),
                    ("roformer-precision-v1", "second"),
                ],
            )
            data = json.loads(progress.read_text(encoding="utf-8"))
            self.assertEqual(data["completed"], 4)
            self.assertEqual(data["failed"], 0)

            calls.clear()
            resumed = run_prepared_benchmark(manifest, separator=separate)

            self.assertEqual(calls, [])
            resumed_data = json.loads(resumed.read_text(encoding="utf-8"))
            self.assertEqual(resumed_data["skipped"], 4)

    def test_retries_output_when_recorded_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _write(root / "clips" / "first.wav", b"first")
            manifest = _write_manifest(root, source)
            calls = 0

            def separate(
                input_path: Path,
                output: Path,
                recipe: SeparationRecipe,
                progress,
            ) -> SeparationResult:
                nonlocal calls
                calls += 1
                vocals = _write(output / "vocals.wav", f"vocals-{calls}".encode())
                instrumental = _write(output / "no_vocals.wav", b"music")
                return SeparationResult(input_path, output, vocals, instrumental, recipe)

            run_prepared_benchmark(
                manifest,
                candidate_ids=("htdemucs",),
                separator=separate,
            )
            output = root / "results" / "htdemucs" / "first" / "vocals.wav"
            output.write_bytes(b"changed")

            run_prepared_benchmark(
                manifest,
                candidate_ids=("htdemucs",),
                separator=separate,
            )

            self.assertEqual(calls, 2)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_manifest(root: Path, *clips: Path) -> Path:
    manifest = root / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "benchmark_id": "test",
                "definition_sha256": "a" * 64,
                "root": str(root),
                "clips": [
                    {
                        "clip_id": source.stem,
                        "title": source.stem,
                        "path": str(source),
                        "sha256": file_sha256(source),
                    }
                    for source in clips
                ],
                "candidates": [
                    {
                        "candidate_id": "htdemucs",
                        "label": "HTDemucs",
                        "recipe_id": "demucs-standard-v1",
                    },
                    {
                        "candidate_id": "bs-roformer",
                        "label": "BS-RoFormer",
                        "recipe_id": "roformer-precision-v1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    unittest.main()
