from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    RvcComputeBackend,
    RvcHardwareSelection,
    RvcSupportLevel,
)
from jang_app.services.system_environment import (
    MemoryInformation,
    ProcessorInformation,
    collect_pc_environment,
)


class SystemEnvironmentTests(unittest.TestCase):
    def test_collects_selected_adapter_and_memory_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            adapter = GraphicsAdapter("RTX Test", "nvidia", adapter_ram=8 * 1024**3)
            selection = RvcHardwareSelection(
                "cu128",
                RvcComputeBackend.CUDA,
                RvcSupportLevel.FULL_GPU,
                adapter,
                RvcComputeBackend.CUDA,
            )
            with (
                patch(
                    "jang_app.services.system_environment.detect_graphics_adapters",
                    return_value=(adapter,),
                ),
                patch(
                    "jang_app.services.system_environment.recorded_hardware_selection",
                    return_value=selection,
                ),
                patch(
                    "jang_app.services.system_environment._processor_information",
                    return_value=ProcessorInformation("Test CPU", 8, 16, "AMD64"),
                ),
                patch(
                    "jang_app.services.system_environment._memory_information",
                    return_value=MemoryInformation(32 * 1024**3, 8 * 1024**3),
                ),
            ):
                snapshot = collect_pc_environment(paths)

        self.assertEqual(snapshot.selected_adapter_name, "RTX Test")
        self.assertEqual(snapshot.selected_profile, "cu128")
        self.assertEqual(snapshot.processor.physical_cores, 8)
        self.assertEqual(snapshot.memory.used_percent, 75)


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={
            "JJZERO_DATA_ROOT": str(root / "appdata"),
            "JJZERO_STORAGE_ROOT": str(root / "storage"),
            "USERPROFILE": str(root / "user"),
        },
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=root / "source",
    )


if __name__ == "__main__":
    unittest.main()
