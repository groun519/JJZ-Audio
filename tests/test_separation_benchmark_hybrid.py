from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_benchmark_hybrid import render_hybrid_benchmark


class SeparationBenchmarkHybridTests(unittest.TestCase):
    def test_renders_each_pair_and_reuses_current_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, plan = _fixture(root)
            calls: list[tuple[Path, Path]] = []

            def mix(converted: Path, instrumental: Path, output: Path) -> Path:
                calls.append((converted, instrumental))
                output.write_bytes(converted.read_bytes() + instrumental.read_bytes())
                return output

            hybrid_manifest = render_hybrid_benchmark(
                manifest, plan, mixer=mix
            )
            render_hybrid_benchmark(manifest, plan, mixer=mix)

            self.assertEqual(len(calls), 2)
            rendered = json.loads(hybrid_manifest.read_text(encoding="utf-8"))
            self.assertEqual(rendered["status"], "completed")
            self.assertEqual(rendered["mix"]["instrumental_volume"], 0.35)
            candidates = rendered["clips"][0]["candidates"]
            self.assertEqual(
                {candidate["candidate_id"] for candidate in candidates},
                {"incumbent", "recommended-hybrid"},
            )
            self.assertTrue(
                all(Path(candidate["final_mix"]["path"]).is_file() for candidate in candidates)
            )


def _fixture(root: Path) -> tuple[Path, Path]:
    definition_hash = "a" * 64
    source = _write(root / "clips" / "clip.wav", b"source")
    converted = _write(
        root / "results" / "kim" / "clip" / "downstream" / "converted.wav",
        b"converted",
    )
    for candidate_id, instrumental_data in (("kim", b"kim"), ("ht", b"ht")):
        result_root = root / "results" / candidate_id / "clip"
        instrumental = _write(result_root / "no_vocals.wav", instrumental_data)
        _write_json(
            result_root / "benchmark-result.json",
            {
                "status": "completed",
                "definition_sha256": definition_hash,
                "outputs": {"instrumental": _record(instrumental)},
            },
        )
    _write_json(
        root / "results" / "kim" / "clip" / "downstream" / "benchmark-render.json",
        {
            "status": "completed",
            "definition_sha256": definition_hash,
            "outputs": {"converted_vocals": _record(converted)},
        },
    )
    manifest = _write_json(
        root / "benchmark.json",
        {
            "benchmark_id": "test",
            "definition_sha256": definition_hash,
            "root": str(root),
            "clips": [
                {
                    "clip_id": "clip",
                    "title": "Clip",
                    "role": "Test",
                    **_record(source),
                }
            ],
            "candidates": [
                {"candidate_id": "kim"},
                {"candidate_id": "ht"},
            ],
        },
    )
    plan = _write_json(
        root / "plan.json",
        {
            "schema": 1,
            "benchmark_id": "test",
            "clips": [
                {
                    "clip_id": "clip",
                    "candidates": [
                        {
                            "candidate_id": "incumbent",
                            "vocal_candidate_id": "kim",
                            "instrumental_candidate_id": "kim",
                        },
                        {
                            "candidate_id": "recommended-hybrid",
                            "vocal_candidate_id": "kim",
                            "instrumental_candidate_id": "ht",
                        },
                    ],
                }
            ],
        },
    )
    return manifest, plan


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": file_sha256(path), "size": path.stat().st_size}


if __name__ == "__main__":
    unittest.main()
