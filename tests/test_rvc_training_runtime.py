from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.command import CommandResult
from jang_app.services.rvc_training_runtime import (
    RvcTrainingRuntimeInspection,
    inspect_rvc_training_runtime,
    required_rvc_training_paths,
    training_backend_for_profile,
)
from jang_app.services.rvc_hardware import RvcComputeBackend


class RvcTrainingRuntimeTests(unittest.TestCase):
    def test_maps_runtime_profiles_to_supported_training_backends(self) -> None:
        self.assertEqual(training_backend_for_profile("cu128"), RvcComputeBackend.CUDA)
        self.assertEqual(training_backend_for_profile("rocm-win"), RvcComputeBackend.ROCM)
        self.assertEqual(training_backend_for_profile("directml"), RvcComputeBackend.CPU)

    def test_cpu_runtime_is_training_ready_without_cuda(self) -> None:
        inspection = RvcTrainingRuntimeInspection(
            Path("C:/rvc"),
            (),
            cuda_available=False,
            cpu_ready=True,
        )

        self.assertTrue(inspection.ready)
        self.assertFalse(inspection.training_accelerated)
        self.assertEqual(inspection.training_device, "cpu")

    def test_reports_missing_training_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "runtime" / "python.exe").write_bytes(b"python")

            inspection = inspect_rvc_training_runtime(root)

            self.assertFalse(inspection.assets_ready)
            self.assertIn(Path("pretrained_v2/f0G40k.pth"), inspection.missing_paths)
            self.assertIn(Path("extract_feature_print.py"), inspection.missing_paths)
            self.assertIn(Path("lib/jjzero_device.py"), inspection.missing_paths)
            self.assertIn(Path("lib/train/utils.py"), inspection.missing_paths)

    def test_complete_runtime_can_probe_cuda(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_runtime(root)
            calls: list[tuple] = []

            def runner(args, cwd=None):
                calls.append((args, cwd))
                return CommandResult(args, 0, json.dumps({"available": True, "device_count": 1}), "")

            inspection = inspect_rvc_training_runtime(root, check_cuda=True, command_runner=runner)

            self.assertTrue(inspection.ready)
            self.assertTrue(inspection.cuda_available)
            self.assertEqual(inspection.cuda_device_count, 1)
            self.assertEqual(calls[0][1], root.resolve())

    def test_complete_runtime_requires_cuda_probe_for_full_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_runtime(root)

            inspection = inspect_rvc_training_runtime(root)

            self.assertTrue(inspection.assets_ready)
            self.assertFalse(inspection.ready)

    def test_cuda_probe_failure_is_not_reported_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_runtime(root)

            def runner(args, cwd=None):
                return CommandResult(args, 1, "", "torch import failed")

            inspection = inspect_rvc_training_runtime(root, check_cuda=True, command_runner=runner)

            self.assertFalse(inspection.ready)
            self.assertEqual(inspection.cuda_error, "torch import failed")

    def test_blackwell_with_legacy_cu118_runtime_is_not_training_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_runtime(root)

            def runner(args, cwd=None):
                output = {
                    "available": True,
                    "device_count": 1,
                    "torch_version": "2.0.0+cu118",
                    "cuda_version": "11.8",
                    "device_capability": [12, 0],
                    "cuda_arch_list": ["sm_86", "sm_90"],
                }
                return CommandResult(args, 0, json.dumps(output), "")

            inspection = inspect_rvc_training_runtime(root, check_cuda=True, command_runner=runner)

            self.assertFalse(inspection.ready)
            self.assertIn("sm_120", inspection.cuda_error)


def _create_runtime(root: Path) -> None:
    for relative_path in required_rvc_training_paths():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")


if __name__ == "__main__":
    unittest.main()
