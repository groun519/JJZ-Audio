from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jang_app.services.rvc_model_package import RvcModelPackageLayout


_MIN_SPECTROGRAM_BYTES = 4096
_SPECTROGRAM_SIZE_RATIO = 3
_CHECKPOINT_RESERVE_BYTES = 512 * 1024**2
_TRAINING_RUNTIME_RESERVE_BYTES = 7 * 1024**3
_FREE_SPACE_RESERVE_BYTES = 1024**3


class RvcTrainingStorageError(RuntimeError):
    """Raised when the model workspace cannot safely hold training outputs."""


@dataclass(frozen=True)
class RvcTrainingStorageInspection:
    audio_count: int
    corrupt_spectrograms: tuple[Path, ...]
    available_bytes: int
    required_bytes: int

    @property
    def ready(self) -> bool:
        return self.available_bytes >= self.required_bytes


class DiskUsageResult(Protocol):
    free: int


DiskUsage = Callable[[Path], DiskUsageResult]


def inspect_rvc_training_storage(
    layout: RvcModelPackageLayout,
    *,
    disk_usage: DiskUsage = shutil.disk_usage,
) -> RvcTrainingStorageInspection:
    audio_files = tuple(sorted(layout.experiment_dir.glob("0_gt_wavs/*.wav")))
    if not audio_files:
        raise RvcTrainingStorageError("RVC training audio cache is empty.")

    valid_bytes = 0
    corrupt: list[Path] = []
    for audio in audio_files:
        spectrogram = audio.with_suffix(".spec.pt")
        if not spectrogram.is_file():
            continue
        if spectrogram.stat().st_size < _MIN_SPECTROGRAM_BYTES:
            corrupt.append(spectrogram)
        else:
            valid_bytes += spectrogram.stat().st_size

    estimated_cache = sum(audio.stat().st_size for audio in audio_files)
    estimated_cache *= _SPECTROGRAM_SIZE_RATIO
    remaining_cache = max(0, estimated_cache - valid_bytes)
    required = (
        remaining_cache
        + _CHECKPOINT_RESERVE_BYTES
        + _TRAINING_RUNTIME_RESERVE_BYTES
        + _FREE_SPACE_RESERVE_BYTES
    )
    available = disk_usage(layout.root).free
    return RvcTrainingStorageInspection(
        audio_count=len(audio_files),
        corrupt_spectrograms=tuple(corrupt),
        available_bytes=available,
        required_bytes=required,
    )


def prepare_rvc_training_storage(
    layout: RvcModelPackageLayout,
    *,
    disk_usage: DiskUsage = shutil.disk_usage,
) -> RvcTrainingStorageInspection:
    inspection = inspect_rvc_training_storage(layout, disk_usage=disk_usage)
    if not inspection.ready:
        raise RvcTrainingStorageError(
            "Not enough free space for RVC training. "
            f"Required: {_gib(inspection.required_bytes)} GiB, "
            f"available: {_gib(inspection.available_bytes)} GiB."
        )
    for path in inspection.corrupt_spectrograms:
        path.unlink(missing_ok=True)
    return inspection


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f}"
