from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_benchmark_render import render_prepared_benchmark


class SeparationBenchmarkRenderTests(unittest.TestCase):
    def test_renders_conversion_and_mix_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _manifest(root)
            calls: list[str] = []

            def convert(source: Path, output: Path, _settings) -> Path:
                calls.append(f"convert:{source.name}")
                return _write(output / "converted.wav", b"converted")

            def mix(converted: Path, instrumental: Path, output: Path) -> Path:
                calls.append(f"mix:{converted.name}:{instrumental.name}")
                return _write(output, b"mix")

            progress = render_prepared_benchmark(
                manifest,
                converter=convert,
                mixer=mix,
            )

            self.assertEqual(
                calls,
                ["convert:vocals.wav", "mix:converted.wav:no_vocals.wav"],
            )
            data = json.loads(progress.read_text(encoding="utf-8"))
            self.assertEqual(data["completed"], 1)
            render = json.loads(
                (root / "results" / "candidate" / "clip" / "downstream" / "benchmark-render.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(render["status"], "completed")
            self.assertIn("converted_vocals", render["outputs"])
            self.assertIn("final_mix", render["outputs"])

            calls.clear()
            resumed = render_prepared_benchmark(
                manifest,
                converter=convert,
                mixer=mix,
            )
            self.assertEqual(calls, [])
            self.assertEqual(
                json.loads(resumed.read_text(encoding="utf-8"))["skipped"], 1
            )

    def test_rebuilds_when_converted_output_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _manifest(root)
            count = 0

            def convert(_source: Path, output: Path, _settings) -> Path:
                nonlocal count
                count += 1
                return _write(output / f"converted-{count}.wav", str(count).encode())

            def mix(_converted: Path, _instrumental: Path, output: Path) -> Path:
                return _write(output, b"mix")

            render_prepared_benchmark(manifest, converter=convert, mixer=mix)
            render_file = root / "results" / "candidate" / "clip" / "downstream" / "benchmark-render.json"
            render = json.loads(render_file.read_text(encoding="utf-8"))
            Path(render["outputs"]["converted_vocals"]["path"]).write_bytes(b"changed")

            render_prepared_benchmark(manifest, converter=convert, mixer=mix)

            self.assertEqual(count, 2)

    def test_reuses_conversion_when_only_mix_policy_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _manifest(root)
            conversions = 0
            mixes = 0

            def convert(_source: Path, output: Path, _settings) -> Path:
                nonlocal conversions
                conversions += 1
                return _write(output / "converted.wav", b"converted")

            def mix(_converted: Path, _instrumental: Path, output: Path) -> Path:
                nonlocal mixes
                mixes += 1
                return _write(output, f"mix-{mixes}".encode())

            render_prepared_benchmark(manifest, converter=convert, mixer=mix)
            render_file = (
                root
                / "results"
                / "candidate"
                / "clip"
                / "downstream"
                / "benchmark-render.json"
            )
            render = json.loads(render_file.read_text(encoding="utf-8"))
            render["mix"] = {"instrumental_volume": 1.0}
            render_file.write_text(json.dumps(render), encoding="utf-8")

            render_prepared_benchmark(manifest, converter=convert, mixer=mix)

            self.assertEqual(conversions, 1)
            self.assertEqual(mixes, 2)


def _manifest(root: Path) -> Path:
    vocals = _write(root / "results" / "candidate" / "clip" / "vocals.wav", b"vocals")
    instrumental = _write(
        root / "results" / "candidate" / "clip" / "no_vocals.wav", b"instrumental"
    )
    result = root / "results" / "candidate" / "clip" / "benchmark-result.json"
    result.write_text(
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
    model = _write(root / "rvc" / "voice.pth", b"model")
    index = _write(root / "rvc" / "voice.index", b"index")
    manifest = root / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "root": str(root),
                "definition_sha256": "a" * 64,
                "clips": [{"clip_id": "clip"}],
                "candidates": [{"candidate_id": "candidate"}],
                "rvc": {
                    "root": str(root / "rvc"),
                    "voice_model": str(model),
                    "voice_model_sha256": file_sha256(model),
                    "index_file": str(index),
                    "index_sha256": file_sha256(index),
                    "pitch": -12,
                    "f0_method": "rmvpe",
                    "device": "gpu",
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": file_sha256(path), "size": path.stat().st_size}


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


if __name__ == "__main__":
    unittest.main()
