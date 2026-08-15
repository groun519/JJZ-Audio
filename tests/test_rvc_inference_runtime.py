from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.services import rvc_inference_runtime as runtime_module
from jang_app.services.command import CommandResult
from jang_app.services.rvc_cuda_compatibility import cuda_architecture_error
from jang_app.services.rvc_inference_runtime import (
    RvcInferenceCapabilities,
    RvcInferenceRuntimeError,
    select_rvc_inference_device,
)


class RvcInferenceRuntimeTests(unittest.TestCase):
    def test_directml_probe_requires_complete_rmvpe_runtime(self) -> None:
        self.assertIn("DmlExecutionProvider", runtime_module._DIRECTML_PROBE)
        self.assertIn("runtime/rmvpe.onnx", runtime_module._DIRECTML_PROBE)

    def test_skips_accelerator_probe_when_cpu_runtime_is_broken(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "runtime" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            result = CommandResult(
                (),
                0,
                json.dumps(
                    {
                        "imports_ready": False,
                        "cpu_ready": False,
                        "faiss_ready": False,
                        "torch_version": "",
                        "detail": "ImportError: fairseq",
                    }
                ),
                "",
            )
            runtime_module.clear_rvc_inference_probe_cache()
            with patch.object(runtime_module, "_run_probe", return_value=result) as probe:
                capabilities = runtime_module.probe_rvc_inference_runtime(root)

            self.assertFalse(capabilities.runtime_ready)
            self.assertEqual(probe.call_count, 1)
            self.assertIn("skipped", capabilities.cuda_detail.lower())
            runtime_module.clear_rvc_inference_probe_cache()

    def test_selects_requested_cuda_device_when_probe_passes(self) -> None:
        capabilities = _capabilities(cuda_available=True, cuda_ready=True, device_count=1)

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cuda:0",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "cuda:0")
        self.assertFalse(selection.fallback_reason)

    def test_explicit_cuda_fails_when_gpu_is_unavailable(self) -> None:
        capabilities = _capabilities(cuda_available=False, cuda_ready=False)

        with self.assertRaisesRegex(RvcInferenceRuntimeError, "GPU acceleration"):
            select_rvc_inference_device(
                Path("C:/rvc"),
                "cuda:0",
                runtime_probe=lambda _root: capabilities,
            )

    def test_auto_falls_back_to_cpu_when_gpu_is_unavailable(self) -> None:
        capabilities = _capabilities(cuda_available=False, cuda_ready=False)

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "auto",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "cpu")
        self.assertTrue(selection.fallback_reason)

    def test_keeps_explicit_cpu_selection(self) -> None:
        capabilities = _capabilities(cuda_available=True, cuda_ready=True, device_count=1)

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cpu",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "cpu")
        self.assertFalse(selection.fallback_reason)

    def test_auto_selects_directml_when_profile_probe_passes(self) -> None:
        capabilities = _capabilities(cuda_available=False, cuda_ready=False)
        capabilities = replace(
            capabilities,
            directml_available=True,
            directml_ready=True,
            directml_device="privateuseone:0",
        )

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "auto",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "privateuseone:0")

    def test_explicit_directml_fails_when_runtime_is_unavailable(self) -> None:
        capabilities = replace(
            _capabilities(cuda_available=False, cuda_ready=False),
            directml_available=True,
            directml_ready=False,
            directml_detail="DirectML validation failed.",
        )

        with self.assertRaisesRegex(RvcInferenceRuntimeError, "validation failed"):
            select_rvc_inference_device(
                Path("C:/rvc"),
                "directml",
                runtime_probe=lambda _root: capabilities,
            )

    def test_directml_probe_rejects_runtime_when_rmvpe_smoke_test_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "python.exe").write_bytes(b"python")
            (runtime / "jjzero-runtime-profile.json").write_text(
                json.dumps({"profile": "directml"}),
                encoding="utf-8",
            )
            cpu_result = runtime_module.CommandResult(
                (),
                0,
                json.dumps(
                    {
                        "imports_ready": True,
                        "cpu_ready": True,
                        "faiss_ready": True,
                        "torch_version": "2.4.1+cpu",
                        "detail": "",
                    }
                ),
                "",
            )
            directml_result = runtime_module.CommandResult(
                (),
                0,
                json.dumps(
                    {
                        "directml_available": True,
                        "directml_ready": True,
                        "directml_device": "privateuseone:0",
                        "device_name": "AMD Radeon(TM) RX Vega 11 Graphics",
                        "detail": "",
                    }
                ),
                "",
            )
            runtime_module.clear_rvc_inference_probe_cache()
            with (
                patch.object(runtime_module, "_run_probe", side_effect=[cpu_result, directml_result]),
                patch.object(
                    runtime_module,
                    "_run_directml_rmvpe_probe",
                    return_value="DirectML RMVPE probe crashed with Windows status 0xC00000FD.",
                ),
            ):
                capabilities = runtime_module.probe_rvc_inference_runtime(root)
            self.assertTrue(capabilities.directml_available)
            self.assertFalse(capabilities.directml_ready)
            self.assertIn("RMVPE probe", capabilities.directml_detail)
            runtime_module.clear_rvc_inference_probe_cache()

    def test_directml_rmvpe_probe_stages_model_in_its_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "runtime" / "python.exe"
            script = root / "extract_f0_rmvpe.py"
            model = root / "runtime" / "rmvpe.onnx"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            script.write_bytes(b"script")
            model.write_bytes(b"directml-rmvpe")

            def complete_probe(args, **kwargs):
                workspace = Path(kwargs["cwd"])
                self.assertEqual((workspace / "rmvpe.onnx").read_bytes(), b"directml-rmvpe")
                probe_root = Path(args[5])
                for relative in (
                    Path("2a_f0") / "probe.wav.npy",
                    Path("2b-f0nsf") / "probe.wav.npy",
                ):
                    target = probe_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"pitch")
                return CommandResult(tuple(args), 0, "", "")

            with patch.object(runtime_module, "run_command", side_effect=complete_probe):
                detail = runtime_module._run_directml_rmvpe_probe(
                    python,
                    root,
                    "privateuseone:0",
                )

            self.assertEqual(detail, "")

    def test_legacy_cuda_preference_uses_directml_after_amd_migration(self) -> None:
        capabilities = _capabilities(cuda_available=False, cuda_ready=False)
        capabilities = replace(
            capabilities,
            directml_available=True,
            directml_ready=True,
        )

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cuda:0",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "privateuseone:0")

    def test_rejects_runtime_when_cpu_or_faiss_probe_failed(self) -> None:
        capabilities = RvcInferenceCapabilities(
            imports_ready=False,
            cpu_ready=False,
            faiss_ready=False,
            cuda_available=True,
            cuda_ready=True,
            device_count=1,
            cpu_detail="CPU inference crashed with Windows status 0xC0000094.",
        )

        with self.assertRaisesRegex(RvcInferenceRuntimeError, "0xC0000094"):
            select_rvc_inference_device(
                Path("C:/rvc"),
                "cuda:0",
                runtime_probe=lambda _root: capabilities,
            )

    def test_blackwell_rejects_legacy_cu118_runtime(self) -> None:
        detail = cuda_architecture_error(
            "2.0.0+cu118",
            "11.8",
            (12, 0),
            ("sm_80", "sm_86", "sm_90"),
        )

        self.assertIn("sm_120", detail)
        self.assertIn("2.7.1+cu128", detail)

    def test_blackwell_accepts_official_cu128_runtime_profile(self) -> None:
        detail = cuda_architecture_error(
            "2.7.1+cu128",
            "12.8",
            (12, 0),
            ("sm_80", "sm_90", "sm_120"),
        )

        self.assertEqual(detail, "")

    def test_blackwell_cuda_request_does_not_silently_fall_back_to_cpu(self) -> None:
        capabilities = RvcInferenceCapabilities(
            imports_ready=True,
            cpu_ready=True,
            faiss_ready=True,
            cuda_available=True,
            cuda_ready=False,
            device_count=1,
            device_name="NVIDIA GeForce RTX 5070",
            device_capability=(12, 0),
            cuda_detail="RTX 50-series requires Torch 2.7.1+cu128.",
        )

        with self.assertRaisesRegex(RvcInferenceRuntimeError, r"2.7.1\+cu128"):
            select_rvc_inference_device(
                Path("C:/rvc"),
                "cuda:0",
                runtime_probe=lambda _root: capabilities,
            )

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cpu",
            runtime_probe=lambda _root: capabilities,
        )
        self.assertEqual(selection.effective_device, "cpu")


def _capabilities(
    *,
    cuda_available: bool,
    cuda_ready: bool,
    device_count: int = 0,
) -> RvcInferenceCapabilities:
    return RvcInferenceCapabilities(
        imports_ready=True,
        cpu_ready=True,
        faiss_ready=True,
        cuda_available=cuda_available,
        cuda_ready=cuda_ready,
        device_count=device_count,
        device_name="Test GPU" if device_count else "",
    )


if __name__ == "__main__":
    unittest.main()
