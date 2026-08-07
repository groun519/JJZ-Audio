from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_profile_activation import (
    _activation_probe,
    RvcProfileActivationError,
    validate_rvc_profile_activation,
)


class RvcProfileActivationTests(unittest.TestCase):
    def test_directml_probe_requires_onnx_provider_and_rmvpe_model(self) -> None:
        probe = _activation_probe("directml")

        self.assertIn("DmlExecutionProvider", probe)
        self.assertIn("rmvpe.onnx", probe)

    def test_rocm_probe_allows_training_attempt_after_gpu_forward_validation(self) -> None:
        probe = _activation_probe("rocm-win")

        self.assertIn("Conv1d", probe)
        self.assertIn("Conv2d", probe)
        self.assertNotIn("loss.backward()", probe)

    def test_accepts_a_rocm_runtime_after_real_operation_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime(Path(temporary))
            payload = json.dumps(
                {
                    "ready": True,
                    "backend": "rocm",
                    "device_name": "AMD Radeon RX 7900 XTX",
                    "torch": "2.9.1+rocm7.2",
                    "accelerator": "7.2.1",
                    "detail": "",
                }
            )

            result = validate_rvc_profile_activation(
                "rocm-win",
                runtime,
                command_runner=lambda _args, _cwd: subprocess.CompletedProcess((), 0, payload, ""),
            )

            self.assertEqual(result.backend, "rocm")
            self.assertEqual(result.device_name, "AMD Radeon RX 7900 XTX")

    def test_rejects_a_runtime_that_has_no_working_hip_device(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime(Path(temporary))
            payload = json.dumps(
                {
                    "ready": False,
                    "backend": "",
                    "device_name": "",
                    "torch": "2.9.1",
                    "accelerator": "",
                    "detail": "RuntimeError: PyTorch has no HIP runtime",
                }
            )

            with self.assertRaisesRegex(RvcProfileActivationError, "no HIP runtime"):
                validate_rvc_profile_activation(
                    "rocm-win",
                    runtime,
                    command_runner=lambda _args, _cwd: subprocess.CompletedProcess(
                        (), 0, payload, ""
                    ),
                )


def _runtime(root: Path) -> Path:
    (root / "python.exe").write_bytes(b"python")
    return root


if __name__ == "__main__":
    unittest.main()
