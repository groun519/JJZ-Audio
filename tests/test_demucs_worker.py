from __future__ import annotations

import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.pipeline import demucs_engine
from jang_app.pipeline.separation_engine import SeparationRequest
from jang_app.services.separation_recipe import FAST_RECIPE
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
        quality_recipe = replace(
            FAST_RECIPE,
            model="htdemucs_ft",
            shifts=2,
            overlap=0.5,
        )
        command = demucs_engine.build_demucs_command(
            Path("input.wav"),
            Path("output"),
            recipe=quality_recipe,
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

    def test_engine_keeps_native_command_paths_in_short_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ("long title " * 12 + ".wav")
            source.write_bytes(b"source")
            output = root / "managed" / "r_123456789abc"
            commands: list[list[str]] = []

            def run(command, **_kwargs):
                commands.append(command)
                command_source = Path(command[-1])
                command_output = Path(command[command.index("-o") + 1])
                native = command_output / FAST_RECIPE.model / command_source.stem
                native.mkdir(parents=True)
                (native / "vocals.wav").write_bytes(b"vocal")
                (native / "no_vocals.wav").write_bytes(b"music")
                return SimpleNamespace(returncode=0, output="")

            with (
                patch.object(demucs_engine, "TOOL_WORKSPACE_DIR", root / "cache"),
                patch.object(demucs_engine, "require_demucs_tools"),
                patch.object(demucs_engine, "run_command", side_effect=run),
            ):
                result = demucs_engine.DemucsEngine().separate(
                    SeparationRequest(source, output, FAST_RECIPE)
                )

            self.assertEqual(result.job_dir, output.resolve())
            self.assertEqual(result.vocals_path, output.resolve() / "vocals.wav")
            self.assertEqual(result.vocals_path.read_bytes(), b"vocal")
            self.assertEqual(Path(commands[0][-1]).name, "i.wav")
            self.assertNotIn(source.stem, str(result.job_dir))

if __name__ == "__main__":
    unittest.main()
