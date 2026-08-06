from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.hardware_diagnostics_state import (
    hardware_diagnostics_required,
    recorded_hardware_profile,
    recorded_hardware_selection,
    record_hardware_diagnostics,
)
from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    RvcComputeBackend,
    RvcHardwareSelection,
    RvcSupportLevel,
)
from jang_app.services.system_diagnostics import SystemDiagnostics


class HardwareDiagnosticsStateTests(unittest.TestCase):
    def test_requires_diagnostics_after_hardware_profile_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            cpu = RvcHardwareSelection(
                "cpu",
                RvcComputeBackend.CPU,
                RvcSupportLevel.CPU,
            )
            amd = RvcHardwareSelection(
                "directml",
                RvcComputeBackend.DIRECTML,
                RvcSupportLevel.INFERENCE_GPU,
                GraphicsAdapter("AMD Radeon RX 6800 XT", "amd"),
            )

            self.assertTrue(hardware_diagnostics_required(paths, selection=cpu))
            record_hardware_diagnostics(paths, SystemDiagnostics(()), selection=cpu)
            self.assertEqual(recorded_hardware_profile(paths), "cpu")
            self.assertFalse(hardware_diagnostics_required(paths, selection=cpu))
            self.assertTrue(hardware_diagnostics_required(paths, selection=amd))

    def test_recorded_selection_restores_adapter_without_reprobing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = discover_app_paths(
                root / "src" / "jang_app",
                environ={"LOCALAPPDATA": str(root / "data")},
                frozen=True,
                executable=root / "app" / "JJZero Audio.exe",
            )
            expected = RvcHardwareSelection(
                "cu118",
                RvcComputeBackend.CUDA,
                RvcSupportLevel.FULL_GPU,
                GraphicsAdapter(
                    "NVIDIA GeForce GTX 1650",
                    "nvidia",
                    "PCI\\VEN_10DE",
                    "32.0.15",
                    4 * 1024**3,
                ),
                RvcComputeBackend.CUDA,
                "CUDA runtime selected.",
            )

            record_hardware_diagnostics(
                paths,
                SystemDiagnostics(()),
                selection=expected,
            )
            recorded = recorded_hardware_selection(paths)

            self.assertIsNotNone(recorded)
            assert recorded is not None
            self.assertEqual(recorded.profile, "cu118")
            self.assertEqual(recorded.training_backend, RvcComputeBackend.CUDA)
            self.assertEqual(recorded.adapter, expected.adapter)


if __name__ == "__main__":
    unittest.main()
