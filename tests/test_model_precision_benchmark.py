from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.pipeline.rvc_convert import RvcConversionError
from jang_app.services.model_precision_benchmark import (
    REFERENCE_CENTER_MIDI,
    load_cached_model_precision_benchmark,
    run_model_precision_benchmark,
)
from jang_app.services.rvc_model_workspace import RvcModelWorkspace


class ModelPrecisionBenchmarkTests(unittest.TestCase):
    def test_precise_benchmark_builds_expected_shift_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference-model")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            progress_updates: list[tuple[int, int, str]] = []

            with patch(
                "jang_app.services.model_precision_benchmark.convert_vocal_with_rvc",
                side_effect=_fake_convert,
            ):
                result = run_model_precision_benchmark(
                    workspace.root,
                    record,
                    progress=lambda completed, total, label: progress_updates.append(
                        (completed, total, label)
                    ),
                )

            self.assertEqual(result.best_shift_semitones, 0)
            self.assertEqual(
                (result.recommended_low_shift, result.recommended_high_shift),
                (-4, 4),
            )
            self.assertEqual(
                (result.usable_low_shift, result.usable_high_shift),
                (-8, 8),
            )
            self.assertEqual(result.stable_point_count, 9)
            self.assertEqual(result.caution_point_count, 8)
            self.assertEqual(result.failed_jobs, 96)
            self.assertEqual(progress_updates[-1], (147, 147, "complete"))

            cached = load_cached_model_precision_benchmark(workspace.root, record)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.best_shift_semitones, 0)

    def test_precise_benchmark_uses_execution_runtime_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference-model")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)
            record = replace(record, runtime_root=root / "missing-runtime")
            execution_runtime = root / "app-runtime"
            execution_runtime.mkdir()

            with patch(
                "jang_app.services.model_precision_benchmark.convert_vocal_with_rvc",
                side_effect=_fake_convert,
            ):
                result = run_model_precision_benchmark(
                    workspace.root,
                    record,
                    execution_runtime_root=execution_runtime,
                )

            self.assertEqual(result.best_shift_semitones, 0)

    def test_cached_benchmark_invalidates_when_model_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "voice.pth"
            model_file.write_bytes(b"inference-model")
            workspace = RvcModelWorkspace(root / "models")
            record = workspace.link_inference_file(model_file)

            with patch(
                "jang_app.services.model_precision_benchmark.convert_vocal_with_rvc",
                side_effect=_fake_convert,
            ):
                run_model_precision_benchmark(workspace.root, record)

            self.assertIsNotNone(load_cached_model_precision_benchmark(workspace.root, record))

            model_file.write_bytes(b"changed-inference-model")
            refreshed = workspace.records()[0]

            self.assertIsNone(load_cached_model_precision_benchmark(workspace.root, refreshed))


def _fake_convert(input_path: Path, output_dir: Path, settings, progress_callback=None):
    shift = int(settings.pitch)
    if abs(shift) > 8:
        raise RvcConversionError("benchmark shift failed")
    bias = 0.0 if abs(shift) <= 4 else 1.6
    output_path = output_dir / f"{input_path.stem}_{shift:+d}.wav"
    _write_tone(output_path, REFERENCE_CENTER_MIDI + shift + bias)
    if progress_callback is not None:
        progress_callback(100)
    return SimpleNamespace(output_path=output_path)


def _write_tone(path: Path, midi_note: float) -> None:
    sample_rate = 40_000
    duration = 0.65
    time = np.arange(round(sample_rate * duration), dtype=np.float64) / sample_rate
    frequency = 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))
    envelope = np.sin(np.pi * np.clip(np.linspace(0.0, 1.0, len(time)), 0.0, 1.0)) ** 0.75
    audio = (
        0.32 * np.sin(2 * np.pi * frequency * time)
        + 0.14 * np.sin(2 * np.pi * frequency * 2 * time)
        + 0.06 * np.sin(2 * np.pi * frequency * 3 * time)
    ) * envelope
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")


if __name__ == "__main__":
    unittest.main()
