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

            checks = {check.key: check for check in diagnostics.checks}
            self.assertTrue(diagnostics.ready)
            self.assertEqual(checks["cuda"].status, DiagnosticStatus.PASS)
            self.assertEqual(checks["cuda"].detail, "AMD Radeon RX 6800 XT")
            self.assertEqual(checks["training_device"].status, DiagnosticStatus.PASS)
            self.assertIn("CPU training", checks["training_device"].detail)

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
            checks = {check.key: check for check in diagnostics.checks}
            self.assertIn("ROCm", checks["ai_runtime"].detail)
            self.assertEqual(checks["training_device"].status, DiagnosticStatus.SKIPPED)

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

            checks = {check.key: check for check in diagnostics.checks}
            self.assertTrue(diagnostics.ready)
            self.assertEqual(checks["cuda"].status, DiagnosticStatus.WARNING)
            self.assertIn("HIP unavailable", checks["cuda"].detail)
            self.assertEqual(checks["training_device"].status, DiagnosticStatus.WARNING)

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
            checks = {check.key: check for check in diagnostics.checks}
            self.assertEqual(checks["cuda"].detail, "Test GPU")
            self.assertEqual(checks["training_device"].detail, "Test GPU")

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

    def test_missing_runtime_requires_install_without_reporting_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")

            diagnostics = run_system_diagnostics(paths)
            statuses = {check.key: check.status for check in diagnostics.checks}

            self.assertFalse(diagnostics.ready)
            self.assertEqual(statuses["ffmpeg"], DiagnosticStatus.REQUIRED)
            self.assertEqual(statuses["rvc_assets"], DiagnosticStatus.REQUIRED)
            self.assertEqual(statuses["cuda"], DiagnosticStatus.SKIPPED)
            self.assertEqual(statuses["training_device"], DiagnosticStatus.SKIPPED)

    def test_incomplete_managed_runtime_is_reported_as_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")
            paths.runtime_root.mkdir(parents=True, exist_ok=True)
            (paths.runtime_root / "runtime-state.json").write_text(
                '{"schema_version": 1, "version": "1"}',
                encoding="utf-8",
            )

            diagnostics = run_system_diagnostics(paths)
            checks = {check.key: check for check in diagnostics.checks}

            self.assertEqual(checks["ffmpeg"].status, DiagnosticStatus.FAIL)
            self.assertEqual(checks["ai_runtime"].status, DiagnosticStatus.FAIL)
            self.assertEqual(checks["cuda"].status, DiagnosticStatus.SKIPPED)
            self.assertEqual(checks["training_device"].status, DiagnosticStatus.SKIPPED)

    def test_reports_each_diagnostic_stage_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_storage_layout(_paths(root), root / "media")
            stages: list[tuple[str, int, int]] = []

            run_system_diagnostics(paths, stage_reporter=lambda *stage: stages.append(stage))

            self.assertEqual(
                stages,
                [
                    ("storage", 1, 7),
                    ("ffmpeg", 2, 7),
                    ("demucs", 3, 7),
                    ("rvc_assets", 4, 7),
                    ("ai_runtime", 5, 7),
                    ("cuda", 6, 7),
                    ("training_device", 7, 7),
                ],
            )

    def test_broken_cpu_runtime_skips_hardware_profile_detection(self) -> None:
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
                cpu_detail="Torch import failed.",
            )

            diagnostics = run_system_diagnostics(
                paths,
                runtime_probe=lambda _root: capabilities,
                profile_detector=lambda: self.fail("hardware profile should not be detected"),
            )
            checks = {check.key: check for check in diagnostics.checks}

            self.assertEqual(checks["ai_runtime"].status, DiagnosticStatus.FAIL)
            self.assertEqual(checks["cuda"].status, DiagnosticStatus.SKIPPED)
            self.assertEqual(checks["training_device"].status, DiagnosticStatus.SKIPPED)

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
            self.assertEqual(statuses["training_device"], DiagnosticStatus.WARNING)
            checks = {check.key: check for check in diagnostics.checks}
            self.assertIn("Select CPU explicitly", checks["cuda"].detail)

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
        runtime / "rvc" / "runtime" / "python3.dll",
        runtime / "rvc" / "runtime" / "Lib" / "site-packages" / "torch" / "__init__.py",
        runtime / "rvc" / "runtime" / "Lib" / "site-packages" / "torchaudio" / "__init__.py",
        runtime
        / "rvc"
        / "runtime"
        / "jjzero-roformer-packages"
        / "audio_separator"
        / "__init__.py",
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
