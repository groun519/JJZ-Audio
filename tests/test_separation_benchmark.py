from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.managed_files import file_sha256
from jang_app.services.separation_benchmark import (
    SeparationBenchmarkError,
    load_benchmark_definition,
    prepare_benchmark,
)
from jang_app.services.settings import RvcSettings


class SeparationBenchmarkTests(unittest.TestCase):
    def test_prepares_library_and_override_clips_with_fixed_rvc_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            library_source = workspace / "library" / "songs" / "song-a" / "source.wav"
            override_source = root / "override.wav"
            _write_audio(library_source, seconds=2)
            _write_audio(override_source, seconds=2)
            _write_song_manifest(library_source.parent, "song-a-id", "source.wav")

            rvc_root = root / "rvc"
            model = rvc_root / "weights" / "voice.pth"
            index = rvc_root / "logs" / "voice" / "voice.index"
            _write_bytes(model, b"model")
            _write_bytes(index, b"index")
            definition_path = root / "definition.json"
            _write_definition(
                definition_path,
                library_hash=file_sha256(library_source),
                override_hash=file_sha256(override_source),
                model_hash=file_sha256(model),
                index_hash=file_sha256(index),
            )

            manifest_path = prepare_benchmark(
                definition_path,
                workspace,
                root / "research",
                RvcSettings(
                    root=rvc_root,
                    voice_model=str(model),
                    index_file=str(index),
                    pitch=-12,
                    device="gpu",
                    f0_method="rmvpe",
                ),
                source_overrides={"external": override_source},
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["benchmark_id"], "test-benchmark")
            self.assertEqual(len(manifest["clips"]), 2)
            self.assertEqual(manifest["rvc"]["pitch"], -12)
            for clip in manifest["clips"]:
                path = Path(clip["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(round(sf.info(path).duration, 1), 1.0)

    def test_rejects_unknown_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "definition.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "benchmark_id": "invalid",
                        "title": "Invalid",
                        "clips": [
                            {
                                "clip_id": "clip",
                                "title": "Clip",
                                "role": "Test",
                                "source": {
                                    "kind": "override",
                                    "source_key": "audio",
                                    "sha256": "0" * 64,
                                },
                                "start_ms": 0,
                                "end_ms": 1000,
                            }
                        ],
                        "rvc": {
                            "model_name": "voice.pth",
                            "model_sha256": "0" * 64,
                            "index_name": "voice.index",
                            "index_sha256": "0" * 64,
                            "pitch": -12,
                            "f0_method": "rmvpe",
                            "device": "gpu",
                        },
                        "candidates": [
                            {
                                "candidate_id": "unknown",
                                "label": "Unknown",
                                "recipe_id": "unknown-recipe",
                            }
                        ],
                        "review_dimensions": ["vocal_completeness"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SeparationBenchmarkError):
                load_benchmark_definition(path)


def _write_audio(path: Path, *, seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.linspace(-0.25, 0.25, 44_100 * seconds, dtype=np.float32)
    sf.write(path, np.column_stack((samples, samples)), 44_100, subtype="PCM_16")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_song_manifest(path: Path, song_id: str, audio: str) -> None:
    (path / "song.json").write_text(
        json.dumps(
            {
                "version": 1,
                "id": song_id,
                "title": "Library song",
                "removed": False,
                "source": {"audio": audio},
            }
        ),
        encoding="utf-8",
    )


def _write_definition(
    path: Path,
    *,
    library_hash: str,
    override_hash: str,
    model_hash: str,
    index_hash: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "benchmark_id": "test-benchmark",
                "title": "Test benchmark",
                "clips": [
                    {
                        "clip_id": "library",
                        "title": "Library",
                        "role": "Library resolution",
                        "source": {
                            "kind": "library",
                            "song_id": "song-a-id",
                            "sha256": library_hash,
                        },
                        "start_ms": 0,
                        "end_ms": 1000,
                    },
                    {
                        "clip_id": "override",
                        "title": "Override",
                        "role": "Override resolution",
                        "source": {
                            "kind": "override",
                            "source_key": "external",
                            "sha256": override_hash,
                        },
                        "start_ms": 500,
                        "end_ms": 1500,
                    },
                ],
                "rvc": {
                    "model_name": "voice.pth",
                    "model_sha256": model_hash,
                    "index_name": "voice.index",
                    "index_sha256": index_hash,
                    "pitch": -12,
                    "f0_method": "rmvpe",
                    "device": "gpu",
                },
                "candidates": [
                    {
                        "candidate_id": "htdemucs",
                        "label": "HTDemucs",
                        "recipe_id": "demucs-standard-v1",
                    }
                ],
                "review_dimensions": ["vocal_completeness"],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
