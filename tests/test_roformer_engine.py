from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.pipeline import roformer_engine
from jang_app.pipeline.separation_engine import SeparationRequest
from jang_app.services.separation_recipe import (
    EFFECT_REMOVAL_RECIPE,
    PRECISION_RECIPE,
    VOCAL_MELBAND_RECIPE,
)


class RoFormerEngineTests(unittest.TestCase):
    def test_command_uses_managed_model_and_output_directories(self) -> None:
        source = Path("input song.wav")
        output = Path("output folder")

        command = roformer_engine.build_roformer_command(
            source,
            output,
            PRECISION_RECIPE,
        )

        self.assertEqual(command[1:3], ["-c", roformer_engine._CLI_ENTRYPOINT])
        self.assertEqual(command[3], str(source))
        self.assertEqual(
            command[command.index("--model_filename") + 1],
            PRECISION_RECIPE.model,
        )
        self.assertEqual(command[command.index("--output_dir") + 1], str(output))
        self.assertEqual(
            command[command.index("--model_file_dir") + 1],
            str(roformer_engine.ROFORMER_MODEL_DIR),
        )

    def test_frozen_command_uses_shared_ai_runtime_python(self) -> None:
        frozen_paths = replace(roformer_engine.APP_PATHS, is_frozen=True)
        runtime_python = Path(r"C:\JJZero\runtime\rvc\runtime\python.exe")
        with (
            patch.object(roformer_engine, "APP_PATHS", frozen_paths),
            patch.object(roformer_engine, "RVC_PYTHON_EXE", runtime_python),
        ):
            command = roformer_engine.build_roformer_command(
                Path("input.wav"),
                Path("output"),
                PRECISION_RECIPE,
            )

        self.assertEqual(command[0], str(runtime_python))

    def test_progress_is_staged_and_monotonic(self) -> None:
        updates: list[int] = []
        callback = roformer_engine.build_roformer_progress_callback(updates.append)

        callback("Loading model")
        callback(" 10%")
        callback(" 100%")
        callback("Starting separation process")
        callback(" 75%")
        callback(" 100%")

        self.assertEqual(updates, sorted(updates))
        self.assertEqual(updates[0], 5)
        self.assertIn(35, updates)
        self.assertIn(45, updates)
        self.assertEqual(updates[-1], 92)

    def test_environment_prioritizes_isolated_precision_packages(self) -> None:
        package_dir = Path(r"C:\JJZero\runtime\rvc\runtime\jjzero-roformer-packages")
        with (
            patch.object(roformer_engine, "ROFORMER_PACKAGE_DIR", package_dir),
            patch.dict("os.environ", {"PYTHONPATH": r"C:\existing"}, clear=False),
        ):
            environment = roformer_engine.build_roformer_environment()

        self.assertEqual(
            environment["PYTHONPATH"].split(roformer_engine.os.pathsep),
            [str(package_dir), r"C:\existing"],
        )

    def test_frozen_runtime_accepts_precision_package_in_site_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime_python = root / "runtime" / "python.exe"
            runtime_python.parent.mkdir(parents=True)
            runtime_python.write_bytes(b"python")
            package = (
                runtime_python.parent
                / "Lib"
                / "site-packages"
                / "audio_separator"
                / "__init__.py"
            )
            package.parent.mkdir(parents=True)
            package.write_bytes(b"package")
            frozen_paths = replace(roformer_engine.APP_PATHS, is_frozen=True)

            with (
                patch.object(roformer_engine, "APP_PATHS", frozen_paths),
                patch.object(roformer_engine, "RVC_PYTHON_EXE", runtime_python),
                patch.object(
                    roformer_engine,
                    "ROFORMER_PACKAGE_DIR",
                    runtime_python.parent / "jjzero-roformer-packages",
                ),
                patch.object(roformer_engine, "require_executable"),
            ):
                roformer_engine.require_roformer_tools()

    def test_outputs_are_normalized_to_application_stem_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vocal = root / "song_(Vocals)_model.wav"
            instrumental = root / "song_(Instrumental)_model.wav"
            vocal.write_bytes(b"vocal")
            instrumental.write_bytes(b"instrumental")

            vocals_path, accompaniment_path = roformer_engine.normalize_roformer_outputs(
                root
            )

            self.assertEqual(vocals_path.name, "vocals.wav")
            self.assertEqual(accompaniment_path.name, "no_vocals.wav")
            self.assertEqual(vocals_path.read_bytes(), b"vocal")
            self.assertEqual(accompaniment_path.read_bytes(), b"instrumental")

    def test_effect_outputs_are_normalized_to_dry_vocal_and_removed_ambience(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "song_(No Reverb)_model.wav").write_bytes(b"dry")
            (root / "song_(Reverb)_model.wav").write_bytes(b"ambience")

            dry_path, effect_path = roformer_engine.normalize_roformer_effect_outputs(root)

            self.assertEqual(dry_path.read_bytes(), b"dry")
            self.assertEqual(effect_path.read_bytes(), b"ambience")

    def test_effect_outputs_accept_legacy_runtime_vocal_stem_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "song_(Vocals)_model.wav").write_bytes(b"dry")
            (root / "song_(Instrumental)_model.wav").write_bytes(b"ambience")

            dry_path, effect_path = roformer_engine.normalize_roformer_effect_outputs(root)

            self.assertEqual(dry_path.read_bytes(), b"dry")
            self.assertEqual(effect_path.read_bytes(), b"ambience")

    def test_deecho_outputs_are_normalized_to_no_echo_and_removed_echo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "song_(No Echo)_model.wav").write_bytes(b"dry")
            (root / "song_(Instrumental)_model.wav").write_bytes(b"echo")

            dry_path, echo_path = roformer_engine.normalize_deecho_outputs(root)

            self.assertEqual(dry_path.name, "no_echo.wav")
            self.assertEqual(echo_path.name, "removed_echo.wav")
            self.assertEqual(dry_path.read_bytes(), b"dry")
            self.assertEqual(echo_path.read_bytes(), b"echo")

    def test_engine_publishes_from_short_workspace_to_managed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / ("long title " * 15 + ".wav")
            source.write_bytes(b"source")
            output = root / "managed" / "r_123456789abc"
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / PRECISION_RECIPE.model).write_bytes(b"model")
            commands: list[list[str]] = []

            def run(command, **_kwargs):
                commands.append(command)
                command_output = Path(command[command.index("--output_dir") + 1])
                command_output.mkdir(parents=True, exist_ok=True)
                (command_output / "i_(Vocals)_model.wav").write_bytes(b"vocal")
                (command_output / "i_(Instrumental)_model.wav").write_bytes(b"music")
                return SimpleNamespace(returncode=0, output="")

            with (
                patch.object(roformer_engine, "TOOL_WORKSPACE_DIR", root / "cache"),
                patch.object(roformer_engine, "ROFORMER_MODEL_DIR", model_dir),
                patch.object(roformer_engine, "require_roformer_tools"),
                patch.object(roformer_engine, "run_command", side_effect=run),
                patch.object(
                    roformer_engine,
                    "postprocess_stems",
                    return_value=("applied", "test"),
                ),
            ):
                result = roformer_engine.RoFormerEngine().separate(
                    SeparationRequest(source, output, PRECISION_RECIPE)
                )

            self.assertEqual(result.job_dir, output.resolve())
            self.assertEqual(result.vocals_path.read_bytes(), b"vocal")
            self.assertEqual(Path(commands[0][3]).name, "i.wav")
            self.assertNotIn(source.stem, str(result.job_dir))

    def test_vocal_melband_assets_are_staged_for_the_legacy_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"source")
            output = root / "result"
            model = root / VOCAL_MELBAND_RECIPE.model
            config = root / "config_vocals_mel_band_roformer_kim.yaml"
            registry = root / "download_checks.json"
            model.write_bytes(b"model")
            config.write_bytes(b"config")
            registry.write_text("{}", encoding="utf-8")
            prepared = SimpleNamespace(files=(model, config), registry=registry)

            def run(command, **_kwargs):
                command_model_dir = Path(
                    command[command.index("--model_file_dir") + 1]
                )
                self.assertTrue((command_model_dir / model.name).is_file())
                self.assertTrue((command_model_dir / config.name).is_file())
                self.assertTrue((command_model_dir / registry.name).is_file())
                command_output = Path(command[command.index("--output_dir") + 1])
                command_output.mkdir(parents=True, exist_ok=True)
                (command_output / "i_(Vocals)_model.wav").write_bytes(b"vocal")
                (command_output / "i_(Instrumental)_model.wav").write_bytes(b"music")
                return SimpleNamespace(returncode=0, output="")

            with (
                patch.object(roformer_engine, "TOOL_WORKSPACE_DIR", root / "cache"),
                patch.object(roformer_engine, "ROFORMER_MODEL_DIR", root / "models"),
                patch.object(roformer_engine, "require_roformer_tools"),
                patch.object(
                    roformer_engine,
                    "roformer_model_assets",
                    return_value=SimpleNamespace(managed_download=True),
                ),
                patch.object(
                    roformer_engine,
                    "prepare_roformer_model_assets",
                    return_value=prepared,
                ),
                patch.object(roformer_engine, "run_command", side_effect=run),
                patch.object(
                    roformer_engine,
                    "postprocess_stems",
                    return_value=("applied", "test"),
                ),
            ):
                result = roformer_engine.RoFormerEngine().separate(
                    SeparationRequest(source, output, VOCAL_MELBAND_RECIPE)
                )

            self.assertEqual(result.recipe, VOCAL_MELBAND_RECIPE)
            self.assertEqual(result.vocals_path.read_bytes(), b"vocal")

    def test_effect_recipe_runs_vocal_separation_then_dereverb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"source")
            output = root / "result"
            model = root / EFFECT_REMOVAL_RECIPE.model
            effect_model = root / EFFECT_REMOVAL_RECIPE.effect_model
            registry = root / "download_checks.json"
            model.write_bytes(b"model")
            effect_model.write_bytes(b"effect")
            registry.write_text("{}", encoding="utf-8")
            commands: list[list[str]] = []

            def run(command, **_kwargs):
                commands.append(command)
                command_output = Path(command[command.index("--output_dir") + 1])
                command_output.mkdir(parents=True, exist_ok=True)
                selected_model = command[command.index("--model_filename") + 1]
                if selected_model == EFFECT_REMOVAL_RECIPE.model:
                    (command_output / "i_(Vocals)_model.wav").write_bytes(b"wet")
                    (command_output / "i_(Instrumental)_model.wav").write_bytes(b"music")
                else:
                    self.assertEqual(Path(command[3]).name, "vocals.wav")
                    (command_output / "i_(Vocals)_model.wav").write_bytes(b"dry")
                    (command_output / "i_(Instrumental)_model.wav").write_bytes(
                        b"ambience"
                    )
                return SimpleNamespace(returncode=0, output="")

            def protect(wet_path, dry_path, output_path):
                self.assertEqual(Path(wet_path).read_bytes(), b"wet")
                self.assertEqual(Path(dry_path).read_bytes(), b"dry")
                Path(output_path).write_bytes(b"protected")
                return SimpleNamespace(detail="vocal-protected 1/1 windows")

            with (
                patch.object(roformer_engine, "TOOL_WORKSPACE_DIR", root / "cache"),
                patch.object(roformer_engine, "ROFORMER_MODEL_DIR", root / "models"),
                patch.object(roformer_engine, "require_roformer_tools"),
                patch.object(
                    roformer_engine,
                    "_prepare_recipe_model_assets",
                    return_value=((model, effect_model), registry),
                ),
                patch.object(roformer_engine, "run_command", side_effect=run),
                patch.object(
                    roformer_engine,
                    "protect_effect_removed_vocals",
                    side_effect=protect,
                ),
                patch.object(
                    roformer_engine,
                    "postprocess_stems",
                    return_value=("applied", "test"),
                ),
            ):
                result = roformer_engine.RoFormerEngine().separate(
                    SeparationRequest(source, output, EFFECT_REMOVAL_RECIPE)
                )

            self.assertEqual(len(commands), 2)
            self.assertEqual(result.vocals_path.read_bytes(), b"protected")
            self.assertEqual(result.accompaniment_path.read_bytes(), b"music")

    def test_effect_recipe_falls_back_to_first_stage_vocal_when_protection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"source")
            output = root / "result"

            def run(command, **_kwargs):
                command_output = Path(command[command.index("--output_dir") + 1])
                command_output.mkdir(parents=True, exist_ok=True)
                selected_model = command[command.index("--model_filename") + 1]
                if selected_model == EFFECT_REMOVAL_RECIPE.model:
                    (command_output / "i_(Vocals)_model.wav").write_bytes(b"wet")
                    (command_output / "i_(Instrumental)_model.wav").write_bytes(b"music")
                else:
                    (command_output / "i_(Vocals)_model.wav").write_bytes(b"dry")
                    (command_output / "i_(Instrumental)_model.wav").write_bytes(b"ambience")
                return SimpleNamespace(returncode=0, output="")

            with (
                patch.object(roformer_engine, "TOOL_WORKSPACE_DIR", root / "cache"),
                patch.object(roformer_engine, "ROFORMER_MODEL_DIR", root / "models"),
                patch.object(roformer_engine, "require_roformer_tools"),
                patch.object(
                    roformer_engine,
                    "_prepare_recipe_model_assets",
                    return_value=((), None),
                ),
                patch.object(roformer_engine, "run_command", side_effect=run),
                patch.object(
                    roformer_engine,
                    "protect_effect_removed_vocals",
                    side_effect=roformer_engine.VocalEffectProtectionError("bad stems"),
                ),
                patch.object(
                    roformer_engine,
                    "postprocess_stems",
                    return_value=("applied", "test"),
                ),
            ):
                result = roformer_engine.RoFormerEngine().separate(
                    SeparationRequest(source, output, EFFECT_REMOVAL_RECIPE)
                )

            self.assertEqual(result.vocals_path.read_bytes(), b"wet")


if __name__ == "__main__":
    unittest.main()
