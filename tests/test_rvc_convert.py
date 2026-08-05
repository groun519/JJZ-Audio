from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.pipeline import rvc_convert
from jang_app.services.command import CommandResult
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_inference_runtime import RvcDeviceSelection, RvcInferenceCapabilities
from jang_app.services.settings import RvcSettings


class RvcConvertTests(unittest.TestCase):
    def test_environment_prefers_bundled_ffmpeg(self) -> None:
        rvc_root = Path("C:/rvc")

        environment = build_rvc_environment(rvc_root)

        path_parts = environment["PATH"].split(os.pathsep)
        self.assertEqual(path_parts[0], str(FFMPEG_BIN_DIR))
        self.assertEqual(path_parts[1], str(rvc_root))
        self.assertEqual(path_parts[2], str(rvc_root / "runtime"))
        self.assertEqual(environment["PYTHONFAULTHANDLER"], "1")

    def test_conversion_uses_effective_cpu_device_after_cuda_fallback(self) -> None:
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
                cuda_available=False,
                cuda_ready=False,
            )
            selection = RvcDeviceSelection("cuda:0", "cpu", capabilities, "CUDA unavailable")
            settings = RvcSettings(root=rvc_root, voice_model="weights/voice.pth", device="cuda:0")

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
            self.assertEqual(args[8], "cpu")
            self.assertTrue(result.output_path.is_file())


if __name__ == "__main__":
    unittest.main()
