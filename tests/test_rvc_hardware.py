from __future__ import annotations

import json
import subprocess
import unittest

from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    RvcComputeBackend,
    RvcSupportLevel,
    probe_graphics_adapters,
    select_rvc_hardware,
)
from jang_app.services.rvc_runtime_profile import NvidiaGpu


class RvcHardwareTests(unittest.TestCase):
    def test_nvidia_is_preferred_on_a_mixed_gpu_pc(self) -> None:
        selection = select_rvc_hardware(
            (
                GraphicsAdapter("AMD Radeon Graphics", "amd"),
                GraphicsAdapter("NVIDIA GeForce RTX 5070", "nvidia"),
            ),
            nvidia_gpus=(NvidiaGpu("NVIDIA GeForce RTX 5070", (12, 0)),),
        )

        self.assertEqual(selection.profile, "cu128")
        self.assertEqual(selection.backend, RvcComputeBackend.CUDA)
        self.assertTrue(selection.training_accelerated)

    def test_supported_amd_card_selects_windows_rocm(self) -> None:
        selection = select_rvc_hardware(
            (GraphicsAdapter("AMD Radeon RX 7900 XTX", "amd"),)
        )

        self.assertEqual(selection.profile, "rocm-win")
        self.assertEqual(selection.backend, RvcComputeBackend.ROCM)
        self.assertEqual(selection.support_level, RvcSupportLevel.FULL_GPU)

    def test_supported_discrete_amd_card_wins_over_integrated_amd_graphics(self) -> None:
        selection = select_rvc_hardware(
            (
                GraphicsAdapter("AMD Radeon Graphics", "amd"),
                GraphicsAdapter("AMD Radeon RX 7900 XTX", "amd"),
            )
        )

        self.assertEqual(selection.profile, "rocm-win")
        self.assertEqual(selection.adapter.name, "AMD Radeon RX 7900 XTX")

    def test_other_amd_card_selects_directml_and_cpu_training(self) -> None:
        selection = select_rvc_hardware(
            (GraphicsAdapter("AMD Radeon RX 6800 XT", "amd"),)
        )

        self.assertEqual(selection.profile, "directml")
        self.assertEqual(selection.backend, RvcComputeBackend.DIRECTML)
        self.assertFalse(selection.training_accelerated)
        self.assertEqual(selection.training_backend, RvcComputeBackend.CPU)

    def test_no_supported_adapter_selects_cpu(self) -> None:
        selection = select_rvc_hardware(
            (GraphicsAdapter("Microsoft Basic Display Adapter", "other"),)
        )

        self.assertEqual(selection.profile, "cpu")
        self.assertEqual(selection.backend, RvcComputeBackend.CPU)

    def test_parses_windows_graphics_adapter_inventory(self) -> None:
        payload = json.dumps(
            [
                {
                    "Name": "AMD Radeon RX 6800 XT",
                    "PNPDeviceID": "PCI\\VEN_1002&DEV_73BF",
                    "DriverVersion": "1.2.3",
                    "AdapterRAM": 16 * 1024**3,
                }
            ]
        )
        result = subprocess.CompletedProcess((), 0, payload, "")

        adapters = probe_graphics_adapters(lambda _args: result)

        self.assertEqual(adapters[0].vendor, "amd")
        self.assertEqual(adapters[0].driver_version, "1.2.3")


if __name__ == "__main__":
    unittest.main()
