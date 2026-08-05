from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.rvc_inference_runtime import (
    RvcInferenceCapabilities,
    RvcInferenceRuntimeError,
    select_rvc_inference_device,
)


class RvcInferenceRuntimeTests(unittest.TestCase):
    def test_selects_requested_cuda_device_when_probe_passes(self) -> None:
        capabilities = _capabilities(cuda_available=True, cuda_ready=True, device_count=1)

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cuda:0",
            runtime_probe=lambda _root: capabilities,
        )

        self.assertEqual(selection.effective_device, "cuda:0")
        self.assertFalse(selection.fallback_reason)

    def test_falls_back_to_cpu_when_cuda_is_unavailable(self) -> None:
        capabilities = _capabilities(cuda_available=False, cuda_ready=False)

        selection = select_rvc_inference_device(
            Path("C:/rvc"),
            "cuda:0",
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
