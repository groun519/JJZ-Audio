from __future__ import annotations

import os
from dataclasses import dataclass

from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_runtime import RvcTrainingRuntimeInspection


@dataclass(frozen=True)
class RvcTrainingDataLoaderSettings:
    workers: int
    prefetch_factor: int = 2
    pin_memory: bool = False
    persistent_workers: bool = False
    timeout_seconds: int = 120

    def validate(self) -> None:
        if self.workers < 0 or self.workers > 8:
            raise ValueError("RVC data loader workers must be between 0 and 8.")
        if self.prefetch_factor <= 0:
            raise ValueError("RVC data loader prefetch factor must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("RVC data loader timeout must be positive.")
        if self.workers == 0 and self.persistent_workers:
            raise ValueError("Persistent RVC workers require at least one worker.")


def recommend_rvc_training_data_loader(
    inspection: RvcTrainingRuntimeInspection,
    *,
    logical_processors: int | None = None,
    windowless_workers_available: bool = True,
) -> RvcTrainingDataLoaderSettings:
    """Choose a stable loader profile without leaving CUDA GPUs starved."""

    if (
        not inspection.training_accelerated
        or inspection.backend == RvcComputeBackend.ROCM
        or bool(inspection.hip_version)
        or not windowless_workers_available
    ):
        return RvcTrainingDataLoaderSettings(workers=0)

    processors = max(1, int(logical_processors or os.cpu_count() or 1))
    if processors >= 8:
        workers = 4
    elif processors >= 4:
        workers = 2
    else:
        workers = 1
    return RvcTrainingDataLoaderSettings(
        workers=workers,
        prefetch_factor=2,
        pin_memory=True,
        persistent_workers=True,
    )


def conservative_rvc_training_data_loader() -> RvcTrainingDataLoaderSettings:
    return RvcTrainingDataLoaderSettings(workers=0)
