from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_performance import (
    recommend_rvc_training_data_loader,
)
from jang_app.services.rvc_training_runtime import RvcTrainingRuntimeInspection


class RvcTrainingPerformanceTests(unittest.TestCase):
    def test_cuda_uses_four_windowless_workers_on_modern_cpu(self) -> None:
        settings = recommend_rvc_training_data_loader(
            _inspection(RvcComputeBackend.CUDA),
            logical_processors=16,
        )

        self.assertEqual(settings.workers, 4)
        self.assertTrue(settings.pin_memory)
        self.assertTrue(settings.persistent_workers)

    def test_cuda_scales_worker_count_for_small_cpu(self) -> None:
        settings = recommend_rvc_training_data_loader(
            _inspection(RvcComputeBackend.CUDA),
            logical_processors=4,
        )

        self.assertEqual(settings.workers, 2)

    def test_missing_pythonw_disables_parallel_workers(self) -> None:
        settings = recommend_rvc_training_data_loader(
            _inspection(RvcComputeBackend.CUDA),
            logical_processors=16,
            windowless_workers_available=False,
        )

        self.assertEqual(settings.workers, 0)
        self.assertFalse(settings.pin_memory)

    def test_rocm_keeps_conservative_loader(self) -> None:
        settings = recommend_rvc_training_data_loader(
            _inspection(RvcComputeBackend.ROCM, hip_version="7.2.1"),
            logical_processors=16,
        )

        self.assertEqual(settings.workers, 0)


def _inspection(
    backend: RvcComputeBackend,
    *,
    hip_version: str = "",
) -> RvcTrainingRuntimeInspection:
    return RvcTrainingRuntimeInspection(
        Path("runtime"),
        (),
        cuda_available=True,
        cuda_device_count=1,
        cpu_ready=True,
        backend=backend,
        hip_version=hip_version,
    )


if __name__ == "__main__":
    unittest.main()
