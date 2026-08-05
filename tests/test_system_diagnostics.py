from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.initial_setup import prepare_storage_layout
from jang_app.services.rvc_inference_runtime import RvcInferenceCapabilities
from jang_app.services.rvc_training_runtime import required_rvc_training_paths
from jang_app.services.system_diagnostics import (
    DiagnosticStatus,
    run_system_diagnostics,
)


class SystemDiagnosticsTests(unittest.TestCase):
    def test_reports_ready_bundled_runtime_and_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")
            _create_runtime(paths.runtime_root)
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=True,
                device_count=1,
                device_name="Test GPU",
                torch_version="2.0.0",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
            )

            self.assertTrue(diagnostics.ready)
            self.assertTrue(all(check.status == DiagnosticStatus.PASS for check in diagnostics.checks))
            self.assertEqual(diagnostics.checks[-1].detail, "Test GPU")

    def test_missing_runtime_is_blocking_but_cuda_is_only_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")

            diagnostics = run_system_diagnostics(paths)
            statuses = {check.key: check.status for check in diagnostics.checks}

            self.assertFalse(diagnostics.ready)
            self.assertEqual(statuses["ffmpeg"], DiagnosticStatus.FAIL)
            self.assertEqual(statuses["rvc_assets"], DiagnosticStatus.FAIL)
            self.assertEqual(statuses["cuda"], DiagnosticStatus.WARNING)

    def test_cpu_ready_without_cuda_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")
            _create_runtime(paths.runtime_root)
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
            )

            diagnostics = run_system_diagnostics(paths, runtime_probe=lambda _root: capabilities)
            statuses = {check.key: check.status for check in diagnostics.checks}

            self.assertTrue(diagnostics.ready)
            self.assertEqual(statuses["ai_runtime"], DiagnosticStatus.PASS)
            self.assertEqual(statuses["cuda"], DiagnosticStatus.WARNING)
            self.assertIn("CPU conversion", diagnostics.checks[-1].detail)

    def test_cpu_runtime_crash_blocks_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")
            _create_runtime(paths.runtime_root)
            capabilities = RvcInferenceCapabilities(
                imports_ready=False,
                cpu_ready=False,
                faiss_ready=False,
                cuda_available=False,
                cuda_ready=False,
                cpu_detail="CPU inference crashed with Windows status 0xC0000094.",
            )

            diagnostics = run_system_diagnostics(paths, runtime_probe=lambda _root: capabilities)
            checks = {check.key: check for check in diagnostics.checks}

            self.assertFalse(diagnostics.ready)
            self.assertEqual(checks["ai_runtime"].status, DiagnosticStatus.FAIL)
            self.assertIn("0xC0000094", checks["ai_runtime"].detail)


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "data"), "USERPROFILE": str(root / "user")},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=root / "source",
    )


def _create_runtime(runtime: Path) -> None:
    for path in (
        runtime / "ffmpeg" / "bin" / "ffmpeg.exe",
        runtime / "ffmpeg" / "bin" / "ffprobe.exe",
        runtime / "demucs" / "torch" / "hub" / "checkpoints" / "955717e8-8726e21a.th",
        runtime / "rvc" / "infer_cli.py",
        runtime / "rvc" / "vc_infer_pipeline.py",
        *(runtime / "rvc" / path for path in required_rvc_training_paths()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")


if __name__ == "__main__":
    unittest.main()
