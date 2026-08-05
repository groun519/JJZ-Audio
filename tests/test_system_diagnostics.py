from __future__ import annotations

import tempfile
import unittest
import json
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
    def test_directml_profile_reports_amd_acceleration_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = prepare_storage_layout(_paths(Path(temporary)), Path(temporary) / "media")
            _create_runtime(paths.runtime_root)
            _write_profile(paths.runtime_root, "directml")
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
                directml_available=True,
                directml_ready=True,
                directml_device_name="AMD Radeon RX 6800 XT",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "directml",
            )

            self.assertTrue(diagnostics.ready)
            self.assertEqual(diagnostics.checks[-1].status, DiagnosticStatus.PASS)

    def test_rocm_profile_requires_hip_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            _create_runtime(paths.runtime_root)
            _write_profile(paths.runtime_root, "rocm-win")
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=True,
                device_count=1,
                device_name="AMD Radeon RX 7900 XTX",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "rocm-win",
            )

            self.assertFalse(diagnostics.ready)
            self.assertIn("ROCm", diagnostics.checks[-2].detail)

    def test_failed_rocm_activation_accepts_directml_as_a_visible_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = prepare_storage_layout(_paths(Path(temporary)), Path(temporary) / "media")
            _create_runtime(paths.runtime_root)
            state = paths.runtime_root / "rvc" / "runtime" / "jjzero-runtime-profile.json"
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profile": "directml",
                        "version": "1",
                        "preferred_profile": "rocm-win",
                        "preferred_version": "1",
                        "activation_status": "fallback",
                        "validation_detail": "RVC rocm-win activation failed: HIP unavailable",
                    }
                ),
                encoding="utf-8",
            )
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=False,
                cuda_ready=False,
                directml_available=True,
                directml_ready=True,
                directml_device_name="AMD Radeon RX 7900 XTX",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "rocm-win",
            )

            self.assertTrue(diagnostics.ready)
            self.assertEqual(diagnostics.checks[-1].status, DiagnosticStatus.WARNING)
            self.assertIn("HIP unavailable", diagnostics.checks[-1].detail)

    def test_blackwell_without_cu128_profile_requires_runtime_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            _create_runtime(paths.runtime_root)
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=False,
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "cu128",
            )

            runtime = next(check for check in diagnostics.checks if check.key == "ai_runtime")
            self.assertEqual(runtime.status, DiagnosticStatus.FAIL)
            self.assertIn("cu128", runtime.detail)

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
                profile_detector=lambda: "cu118",
            )

            self.assertTrue(diagnostics.ready)
            self.assertTrue(all(check.status == DiagnosticStatus.PASS for check in diagnostics.checks))
            self.assertEqual(diagnostics.checks[-1].detail, "Test GPU")

    def test_blackwell_cu128_profile_requires_a_working_cuda_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            _create_runtime(paths.runtime_root)
            profile_state = paths.runtime_root / "rvc" / "runtime" / "jjzero-runtime-profile.json"
            profile_state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profile": "cu128",
                        "version": "1",
                    }
                ),
                encoding="utf-8",
            )
            capabilities = RvcInferenceCapabilities(
                imports_ready=True,
                cpu_ready=True,
                faiss_ready=True,
                cuda_available=True,
                cuda_ready=False,
                cuda_detail="sm_120 convolution failed.",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "cu128",
            )
            checks = {check.key: check for check in diagnostics.checks}

            self.assertFalse(diagnostics.ready)
            self.assertEqual(checks["ai_runtime"].status, DiagnosticStatus.FAIL)
            self.assertIn("sm_120", checks["ai_runtime"].detail)

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

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "cu118",
            )
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

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: "cu118",
            )
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


def _write_profile(runtime: Path, profile: str) -> None:
    state = runtime / "rvc" / "runtime" / "jjzero-runtime-profile.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"schema_version": 1, "profile": profile, "version": "1"}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
