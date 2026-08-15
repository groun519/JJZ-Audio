from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.pipeline import rvc_convert
from jang_app.pipeline.rvc_convert import RvcConversionError
from jang_app.services.command import (
    CommandResult,
    background_command_args,
    hidden_subprocess_kwargs,
)
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_inference_runtime import RvcDeviceSelection, RvcInferenceCapabilities
from jang_app.services.settings import RvcSettings
from jang_app.services.rvc_inference_settings import RvcInferenceSettings


class RvcConvertTests(unittest.TestCase):
    def test_environment_prefers_bundled_ffmpeg(self) -> None:
        rvc_root = Path("C:/rvc")

        environment = build_rvc_environment(rvc_root)

        path_parts = environment["PATH"].split(os.pathsep)
        self.assertEqual(path_parts[0], str(FFMPEG_BIN_DIR))
        self.assertEqual(path_parts[1], str(rvc_root))
        self.assertEqual(path_parts[2], str(rvc_root / "runtime"))
        self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0], str(rvc_root))
        self.assertEqual(environment["PYTHONUTF8"], "1")
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8:replace")
        self.assertEqual(environment["PYTHONFAULTHANDLER"], "1")
        self.assertEqual(environment["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"], "1")
        self.assertEqual(environment["OPENBLAS_NUM_THREADS"], "1")
        self.assertEqual(environment["OMP_NUM_THREADS"], "1")
        self.assertEqual(environment["MKL_NUM_THREADS"], "1")
        self.assertEqual(environment["NUMEXPR_NUM_THREADS"], "1")

    def test_environment_preserves_existing_python_path_after_rvc_root(self) -> None:
        with patch.dict(os.environ, {"PYTHONPATH": r"C:\existing"}, clear=False):
            environment = build_rvc_environment(Path("C:/rvc"))

        self.assertEqual(
            environment["PYTHONPATH"].split(os.pathsep),
            [str(Path("C:/rvc")), r"C:\existing"],
        )

    def test_environment_overrides_legacy_windows_console_encoding(self) -> None:
        with patch.dict(
            os.environ,
            {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949"},
            clear=False,
        ):
            environment = build_rvc_environment(Path("C:/rvc"))

        completed = subprocess.run(
            background_command_args([
                sys.executable,
                "-c",
                "import sys; print(sys.stdout.encoding); print('\u663e\u5361')",
            ]),
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["utf-8", "\u663e\u5361"])

    def test_directml_workspace_links_the_profile_rmvpe_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            workspace = root / "workspace"
            (rvc_root / "configs").mkdir(parents=True)
            (rvc_root / "trainset_preprocess_pipeline_print.py").write_bytes(b"script")
            (rvc_root / "hubert_base.pt").write_bytes(b"hubert")
            (rvc_root / "rmvpe.pt").write_bytes(b"torch-rmvpe")
            (rvc_root / "runtime").mkdir()
            (rvc_root / "runtime" / "rmvpe.onnx").write_bytes(b"directml-rmvpe")

            with patch.object(rvc_convert, "RVC_WORKSPACE_DIR", workspace):
                result = rvc_convert._prepare_rvc_workspace(
                    rvc_root,
                    require_directml_rmvpe=True,
                )

            self.assertEqual(result, workspace)
            self.assertEqual((workspace / "rmvpe.onnx").read_bytes(), b"directml-rmvpe")

    def test_directml_workspace_rejects_an_incomplete_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            workspace = root / "workspace"
            (rvc_root / "configs").mkdir(parents=True)
            (rvc_root / "trainset_preprocess_pipeline_print.py").write_bytes(b"script")
            (rvc_root / "hubert_base.pt").write_bytes(b"hubert")
            (rvc_root / "rmvpe.pt").write_bytes(b"torch-rmvpe")

            with (
                patch.object(rvc_convert, "RVC_WORKSPACE_DIR", workspace),
                self.assertRaisesRegex(RvcConversionError, "missing rmvpe.onnx"),
            ):
                rvc_convert._prepare_rvc_workspace(
                    rvc_root,
                    require_directml_rmvpe=True,
                )

    def test_auto_conversion_uses_effective_cpu_device_without_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            source = root / "vocal.wav"
            model = rvc_root / "weights" / "voice.pth"
            workspace = root / "workspace"
            for path in (
                source,
                model,
                rvc_root / "runtime" / "python.exe",
                rvc_root / "infer_cli.py",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
            workspace.mkdir()
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
            )
            selection = RvcDeviceSelection("auto", "cpu", capabilities, "GPU unavailable")
            settings = RvcSettings(
                root=rvc_root,
                voice_model="weights/voice.pth",
                pitch=-12,
                device="auto",
                inference=RvcInferenceSettings(
                    index_rate=0.62,
                    filter_radius=5,
                    rms_mix_rate=0.4,
                    protect=0.18,
                ),
            )

            def complete_conversion(args, **_kwargs):
                Path(args[5]).write_bytes(b"converted")
                return CommandResult(args, 0, "", "")

            with (
                patch.object(rvc_convert, "select_rvc_inference_device", return_value=selection),
                patch.object(rvc_convert, "_prepare_rvc_workspace", return_value=workspace),
                patch.object(rvc_convert, "run_command", side_effect=complete_conversion) as command,
            ):
                result = rvc_convert.convert_vocal_with_rvc(source, root / "output", settings)

            args = command.call_args.args[0]
            self.assertEqual(args[3], "-12")
            self.assertEqual(args[8], "cpu")
            self.assertEqual(args[10:14], ["0.62", "5", "0.40", "0.18"])
            self.assertTrue(result.output_path.is_file())
            self.assertEqual(result.voice_model, settings.voice_model)
            self.assertEqual(result.pitch, -12)
            self.assertEqual(result.requested_device, settings.device)
            self.assertEqual(result.effective_device, "cpu")
            self.assertEqual(result.inference, settings.inference)

    def test_directml_native_crash_fails_without_cpu_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            source = root / "vocal.wav"
            model = rvc_root / "weights" / "voice.pth"
            workspace = root / "workspace"
            for path in (
                source,
                model,
                rvc_root / "runtime" / "python.exe",
                rvc_root / "infer_cli.py",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
            workspace.mkdir()
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
                directml_available=True,
                directml_ready=True,
                directml_device_name="AMD Radeon(TM) RX Vega 11 Graphics",
            )
            selection = RvcDeviceSelection("gpu", "privateuseone:0", capabilities)
            settings = RvcSettings(
                root=rvc_root,
                voice_model="weights/voice.pth",
                device="gpu",
            )
            def fail_directml(args, **_kwargs):
                return CommandResult(
                    args,
                    3221225725,
                    "loading model",
                    "torch DirectML native runtime stopped",
                )

            with (
                patch.object(rvc_convert, "select_rvc_inference_device", return_value=selection),
                patch.object(rvc_convert, "_prepare_rvc_workspace", return_value=workspace),
                patch.object(
                    rvc_convert,
                    "run_command",
                    side_effect=fail_directml,
                ) as command,
            ):
                with self.assertRaisesRegex(RvcConversionError, "0xC00000FD"):
                    rvc_convert.convert_vocal_with_rvc(
                        source,
                        root / "output",
                        settings,
                    )

            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0][8], "privateuseone:0")

    def test_directml_stack_overflow_failure_is_identified(self) -> None:
        message = rvc_convert._conversion_failure_message(
            3221225725,
            "privateuseone:0",
        )

        self.assertIn("0xC00000FD", message)
        self.assertIn("stack overflow", message)

    def test_long_conversion_automatically_runs_overlapping_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            source = root / "vocal.wav"
            model = rvc_root / "weights" / "voice.pth"
            workspace = root / "workspace"
            sf.write(
                source,
                np.linspace(-0.5, 0.5, 3_000, dtype=np.float32),
                1_000,
                subtype="FLOAT",
            )
            for path in (model, rvc_root / "runtime" / "python.exe", rvc_root / "infer_cli.py"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
            workspace.mkdir()
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
            )
            selection = RvcDeviceSelection("cpu", "cpu", capabilities)
            settings = RvcSettings(root=rvc_root, voice_model="weights/voice.pth", device="cpu")
            progress: list[int] = []

            invocation = 0

            def complete_chunk(args, **_kwargs):
                nonlocal invocation
                invocation += 1
                if invocation == 1:
                    return CommandResult(
                        args,
                        3221225477,
                        "",
                        "faiss.search\nWindows fatal exception: access violation",
                    )
                audio, sample_rate = sf.read(args[4], dtype="float32")
                sf.write(args[5], audio, sample_rate, subtype="PCM_16")
                return CommandResult(args, 0, "", "")

            with (
                patch.object(rvc_convert, "select_rvc_inference_device", return_value=selection),
                patch.object(rvc_convert, "_prepare_rvc_workspace", return_value=workspace),
                patch.object(rvc_convert, "_RVC_AUTO_CHUNK_THRESHOLD_SECONDS", 1.0),
                patch.object(rvc_convert, "_RVC_AUTO_CHUNK_CORE_SECONDS", 1.0),
                patch.object(rvc_convert, "_RVC_AUTO_CHUNK_CONTEXT_SECONDS", 0.1),
                patch.object(rvc_convert, "_RVC_AUTO_CHUNK_BOUNDARY_SEARCH_SECONDS", 0.0),
                patch.object(rvc_convert, "run_command", side_effect=complete_chunk) as command,
            ):
                result = rvc_convert.convert_vocal_with_rvc(
                    source,
                    root / "output",
                    settings,
                    progress_callback=progress.append,
                )

            rendered, sample_rate = sf.read(result.output_path, dtype="float32")
            self.assertEqual(command.call_count, 4)
            self.assertEqual(sample_rate, 1_000)
            self.assertEqual(len(rendered), 3_000)
            self.assertEqual(progress, [33, 67, 100])

    def test_conversion_failure_includes_rvc_process_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            source = root / "vocal.wav"
            model = rvc_root / "weights" / "voice.pth"
            workspace = root / "workspace"
            for path in (source, model, rvc_root / "runtime" / "python.exe", rvc_root / "infer_cli.py"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
            workspace.mkdir()
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=True,
                device_count=1,
                device_name="NVIDIA GeForce RTX 5070",
                torch_version="2.0.0+cu118",
                cuda_version="11.8",
                device_capability=(12, 0),
                cuda_arch_list=("sm_86", "sm_90"),
            )
            selection = RvcDeviceSelection("cuda:0", "cuda:0", capabilities)
            settings = RvcSettings(root=rvc_root, voice_model="weights/voice.pth", device="cuda:0")
            failure = CommandResult(
                ("rvc",),
                1,
                "loading model",
                "RuntimeError: CUDA error: no kernel image is available for execution on the device",
            )

            with (
                patch.object(rvc_convert, "select_rvc_inference_device", return_value=selection),
                patch.object(rvc_convert, "_prepare_rvc_workspace", return_value=workspace),
                patch.object(rvc_convert, "run_command", return_value=failure),
                self.assertRaisesRegex(RvcConversionError, "no kernel image is available"),
            ):
                rvc_convert.convert_vocal_with_rvc(source, root / "output", settings)

    def test_conversion_shortens_output_name_before_legacy_windows_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc_root = root / "rvc"
            long_job_dir = root / ("long-song-folder-" + "x" * 60) / ("separation-result-" + "y" * 50)
            source = long_job_dir / "vocals.wav"
            model = rvc_root / "weights" / "voice-model-with-a-descriptive-name.pth"
            workspace = root / "workspace"
            for path in (source, model, rvc_root / "runtime" / "python.exe", rvc_root / "infer_cli.py"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
            workspace.mkdir()
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=True,
                device_count=1,
                device_name="NVIDIA GeForce RTX 5070",
                torch_version="2.7.1+cu128",
                cuda_version="12.8",
                device_capability=(12, 0),
                cuda_arch_list=("sm_120",),
            )
            selection = RvcDeviceSelection("auto", "cuda:0", capabilities)
            settings = RvcSettings(
                root=rvc_root,
                voice_model="weights/voice-model-with-a-descriptive-name.pth",
                pitch=-12,
                device="auto",
            )
            compact_probe = long_job_dir / "rvc_m12_0000000000.wav"
            safe_path_length = rvc_convert._path_length(compact_probe)
            descriptive_stem = rvc_convert._build_rvc_output_stem(source, settings)
            self.assertGreater(
                rvc_convert._path_length(long_job_dir / f"{descriptive_stem}.wav"),
                safe_path_length,
            )

            def complete_conversion(args, **_kwargs):
                Path(args[5]).write_bytes(b"converted")
                return CommandResult(args, 0, "", "")

            with (
                patch.object(rvc_convert, "select_rvc_inference_device", return_value=selection),
                patch.object(rvc_convert, "_prepare_rvc_workspace", return_value=workspace),
                patch.object(rvc_convert, "_RVC_SAFE_OUTPUT_PATH_LENGTH", safe_path_length),
                patch.object(rvc_convert, "run_command", side_effect=complete_conversion) as command,
            ):
                result = rvc_convert.convert_vocal_with_rvc(source, long_job_dir, settings)

            command_output = Path(command.call_args.args[0][5])
            command_input = Path(command.call_args.args[0][4])
            self.assertNotEqual(command_input, source)
            self.assertNotEqual(command_output, result.output_path)
            self.assertLessEqual(rvc_convert._path_length(command_input), safe_path_length)
            self.assertLessEqual(rvc_convert._path_length(command_output), safe_path_length)
            self.assertTrue(result.output_path.name.startswith("rvc_m12_"))
            self.assertLessEqual(rvc_convert._path_length(result.output_path), safe_path_length)
            self.assertTrue(result.output_path.is_file())

    def test_deep_output_folder_uses_compact_name_without_rejecting_conversion(self) -> None:
        output_dir = Path("C:/") / ("x" * 230)
        settings = RvcSettings(root=Path("C:/rvc"), voice_model="weights/voice.pth")
        descriptive_stem = rvc_convert._build_rvc_output_stem(Path("vocals.wav"), settings)

        stem = rvc_convert._safe_rvc_output_stem(
            output_dir,
            descriptive_stem,
            ".wav",
            settings.pitch,
        )

        self.assertTrue(stem.startswith("rvc_p0_"))

    def test_output_collision_falls_back_to_fixed_length_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / ("x" * 150)
            output_dir.mkdir()
            available_stem_length = 240 - rvc_convert._path_length(output_dir) - len(".wav") - 1
            stem = "v" * available_stem_length
            (output_dir / f"{stem}.wav").write_bytes(b"first")

            result = rvc_convert._next_output_path(output_dir, stem, ".wav")

            self.assertTrue(result.name.startswith("rvc_"))
            self.assertLessEqual(rvc_convert._path_length(result), 240)


if __name__ == "__main__":
    unittest.main()
