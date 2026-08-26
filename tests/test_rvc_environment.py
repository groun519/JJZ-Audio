from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.rvc_environment_status import collect_rvc_environment_status
from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    RvcComputeBackend,
    RvcHardwareSelection,
    RvcSupportLevel,
)
from jang_app.services.rvc_training_runtime import RvcTrainingRuntimeInspection


class RvcEnvironmentTests(unittest.TestCase):
    def test_existing_runtime_is_available_without_managed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            root = paths.runtime_root / "rvc"
            inspection = RvcTrainingRuntimeInspection(root.resolve(), ())
            with (
                patch(
                    "jang_app.services.rvc_environment_status.installed_rvc_runtime_profile",
                    return_value=None,
                ),
                patch(
                    "jang_app.services.rvc_environment_status.recorded_hardware_selection",
                    return_value=_selection(),
                ),
                patch(
                    "jang_app.services.rvc_environment_status.inspect_rvc_training_runtime",
                    return_value=inspection,
                ),
            ):
                snapshot = collect_rvc_environment_status(paths)

        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.installation_kind, "Existing installation")
        self.assertNotIn("incomplete", snapshot.summary.lower())
        self.assertEqual(snapshot.checks[2].status, "info")

    def test_missing_runtime_files_require_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            root = paths.runtime_root / "rvc"
            inspection = RvcTrainingRuntimeInspection(
                root.resolve(),
                (Path("runtime/python.exe"),),
            )
            with (
                patch(
                    "jang_app.services.rvc_environment_status.installed_rvc_runtime_profile",
                    return_value=None,
                ),
                patch(
                    "jang_app.services.rvc_environment_status.recorded_hardware_selection",
                    return_value=_selection(),
                ),
                patch(
                    "jang_app.services.rvc_environment_status.inspect_rvc_training_runtime",
                    return_value=inspection,
                ),
            ):
                snapshot = collect_rvc_environment_status(paths)

        self.assertEqual(snapshot.status, "failed")
        self.assertIn("repair", snapshot.summary.lower())


def _selection() -> RvcHardwareSelection:
    return RvcHardwareSelection(
        "cu118",
        RvcComputeBackend.CUDA,
        RvcSupportLevel.FULL_GPU,
        GraphicsAdapter("RTX Test", "nvidia"),
        RvcComputeBackend.CUDA,
    )


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
