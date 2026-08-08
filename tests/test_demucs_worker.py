from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.pipeline import demucs_engine
from jang_app.services.separation_recipe import HIGH_QUALITY_RECIPE
class DemucsRuntimeTests(unittest.TestCase):
    def test_frozen_separation_uses_the_shared_ai_runtime(self) -> None:
        source = Path("input.wav")
        output = Path("output")

        frozen_paths = replace(demucs_engine.APP_PATHS, is_frozen=True)
        with (
            patch.object(demucs_engine, "APP_PATHS", frozen_paths),
            patch.object(
                demucs_engine,
                "RVC_PYTHON_EXE",
                Path(r"C:\Program Files\JJZero\runtime\rvc\runtime\python.exe"),
            ),
        ):
            command = demucs_engine.build_demucs_command(source, output, "htdemucs")

        self.assertEqual(
            command[:3],
            [
                r"C:\Program Files\JJZero\runtime\rvc\runtime\python.exe",
                "-m",
                "demucs",
            ],
        )
        self.assertEqual(command[-1], str(source))

    def test_frozen_worker_uses_packaged_torch_cache(self) -> None:
        frozen_paths = replace(demucs_engine.APP_PATHS, is_frozen=True)
        with patch.object(demucs_engine, "APP_PATHS", frozen_paths):
            environment = demucs_engine.build_demucs_environment()

        self.assertIsNotNone(environment)
        self.assertEqual(
            environment["TORCH_HOME"],
            str(demucs_engine.DEMUCS_RUNTIME_DIR / "torch"),
        )

    def test_development_worker_uses_the_same_project_owned_model_cache(self) -> None:
        development_paths = replace(demucs_engine.APP_PATHS, is_frozen=False)
        with patch.object(demucs_engine, "APP_PATHS", development_paths):
            environment = demucs_engine.build_demucs_environment()

        self.assertIsNotNone(environment)
        self.assertEqual(
            environment["TORCH_HOME"],
            str(demucs_engine.DEMUCS_RUNTIME_DIR / "torch"),
        )

    def test_quality_recipe_maps_to_explicit_demucs_arguments(self) -> None:
        command = demucs_engine.build_demucs_command(
            Path("input.wav"),
            Path("output"),
            recipe=HIGH_QUALITY_RECIPE,
        )

        self.assertIn("htdemucs_ft", command)
        self.assertEqual(command[command.index("--shifts") + 1], "2")
        self.assertEqual(command[command.index("--overlap") + 1], "0.5")
        self.assertIn("--float32", command)

    def test_multiple_internal_progress_bars_are_aggregated_monotonically(self) -> None:
        updates: list[int] = []
        callback = demucs_engine.build_demucs_progress_callback(
            updates.append,
            expected_cycles=2,
        )

        for output in ("0%|", "50%|", "100%|", "0%|", "50%|", "100%|"):
            callback(output)

        self.assertEqual(updates, sorted(updates))
        self.assertEqual(updates[-1], 100)
        self.assertIn(50, updates)

if __name__ == "__main__":
    unittest.main()
