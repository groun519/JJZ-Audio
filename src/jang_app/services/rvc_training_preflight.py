from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.model_dataset import ModelDataset
from jang_app.services.model_dataset_analysis import ModelDatasetAnalysis
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_runtime import inspect_rvc_training_runtime
from jang_app.services.rvc_training_storage import (
    estimate_rvc_training_required_bytes,
)


class RvcTrainingCheckLevel(StrEnum):
    READY = "ready"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class RvcTrainingCheck:
    key: str
    label: str
    detail: str
    level: RvcTrainingCheckLevel
    values: tuple[tuple[str, object], ...] = ()

    @property
    def format_values(self) -> dict[str, object]:
        return dict(self.values)


@dataclass(frozen=True)
class RvcTrainingPreflight:
    checks: tuple[RvcTrainingCheck, ...]

    @property
    def blockers(self) -> tuple[RvcTrainingCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.level == RvcTrainingCheckLevel.BLOCKER
        )

    @property
    def warnings(self) -> tuple[RvcTrainingCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.level == RvcTrainingCheckLevel.WARNING
        )

    @property
    def can_start(self) -> bool:
        return not self.blockers


class DiskUsageResult(Protocol):
    free: int


DiskUsage = Callable[[Path], DiskUsageResult]


def inspect_rvc_training_preflight(
    *,
    managed_model: bool,
    dataset: ModelDataset,
    analysis: ModelDatasetAnalysis | None,
    runtime_root: Path,
    workspace_root: Path,
    training_backend: RvcComputeBackend,
    adapter_name: str = "",
    adapter_memory_bytes: int = 0,
    disk_usage: DiskUsage = shutil.disk_usage,
) -> RvcTrainingPreflight:
    training_items = dataset.training_items
    ready_items = sum(item.review_state == REVIEW_READY for item in training_items)
    training_paths = tuple(
        path
        for item in training_items
        for path in item.training_paths
    )
    missing_paths = tuple(path for path in training_paths if not path.is_file())

    checks = [
        _model_check(managed_model),
        _materials_check(
            len(training_items),
            ready_items,
            missing_paths,
            training_path_count=len(training_paths),
        ),
        _analysis_check(analysis, len(training_items), ready_items),
        _runtime_check(runtime_root),
        _storage_check(training_paths, workspace_root, disk_usage),
        _device_check(training_backend, adapter_name, adapter_memory_bytes),
    ]
    return RvcTrainingPreflight(tuple(checks))


def basic_rvc_training_preflight(
    *,
    managed_model: bool,
    ready_items: int,
    total_items: int,
) -> RvcTrainingPreflight:
    materials = _materials_check(max(0, total_items), max(0, ready_items), ())
    unavailable = RvcTrainingCheckLevel.WARNING
    return RvcTrainingPreflight(
        (
            _model_check(managed_model),
            materials,
            RvcTrainingCheck(
                "analysis",
                "Material Analysis",
                "Analysis status is not available.",
                unavailable,
            ),
            RvcTrainingCheck(
                "runtime",
                "Training Runtime",
                "Runtime status is not available.",
                unavailable,
            ),
            RvcTrainingCheck(
                "storage",
                "Training Storage",
                "Storage status is not available.",
                unavailable,
            ),
            RvcTrainingCheck(
                "device",
                "Training Device",
                "Device status is not available.",
                unavailable,
            ),
        )
    )


def _model_check(managed_model: bool) -> RvcTrainingCheck:
    if managed_model:
        return RvcTrainingCheck(
            "model",
            "Model",
            "Managed model workspace is ready.",
            RvcTrainingCheckLevel.READY,
        )
    return RvcTrainingCheck(
        "model",
        "Model",
        "Create or import a managed model before training.",
        RvcTrainingCheckLevel.BLOCKER,
    )


def _materials_check(
    total_items: int,
    ready_items: int,
    missing_paths: tuple[Path, ...],
    *,
    training_path_count: int | None = None,
) -> RvcTrainingCheck:
    if total_items <= 0:
        return RvcTrainingCheck(
            "materials",
            "Training Materials",
            "Add training materials before starting.",
            RvcTrainingCheckLevel.BLOCKER,
        )
    if training_path_count == 0:
        return RvcTrainingCheck(
            "materials",
            "Training Materials",
            "No usable training audio was found.",
            RvcTrainingCheckLevel.BLOCKER,
        )
    if missing_paths:
        return RvcTrainingCheck(
            "materials",
            "Training Materials",
            "{count} training files are missing.",
            RvcTrainingCheckLevel.BLOCKER,
            (("count", len(missing_paths)),),
        )
    if ready_items < total_items:
        return RvcTrainingCheck(
            "materials",
            "Training Materials",
            "{ready} of {total} materials are ready.",
            RvcTrainingCheckLevel.BLOCKER,
            (("ready", ready_items), ("total", total_items)),
        )
    return RvcTrainingCheck(
        "materials",
        "Training Materials",
        "All {count} materials are ready.",
        RvcTrainingCheckLevel.READY,
        (("count", total_items),),
    )


def _analysis_check(
    analysis: ModelDatasetAnalysis | None,
    total_items: int,
    ready_items: int,
) -> RvcTrainingCheck:
    if analysis is None:
        return RvcTrainingCheck(
            "analysis",
            "Material Analysis",
            "Run material analysis to review quality before training.",
            RvcTrainingCheckLevel.WARNING,
        )
    if (
        analysis.selected_item_count != total_items
        or analysis.ready_item_count != ready_items
    ):
        return RvcTrainingCheck(
            "analysis",
            "Material Analysis",
            "Materials changed after the last analysis.",
            RvcTrainingCheckLevel.WARNING,
        )
    if analysis.attention_count:
        return RvcTrainingCheck(
            "analysis",
            "Material Analysis",
            "{count} analysis findings need review.",
            RvcTrainingCheckLevel.WARNING,
            (("count", analysis.attention_count),),
        )
    return RvcTrainingCheck(
        "analysis",
        "Material Analysis",
        "Analysis is current with no quality warnings.",
        RvcTrainingCheckLevel.READY,
    )


def _runtime_check(runtime_root: Path) -> RvcTrainingCheck:
    inspection = inspect_rvc_training_runtime(runtime_root, check_cuda=False)
    if inspection.assets_ready:
        return RvcTrainingCheck(
            "runtime",
            "Training Runtime",
            "Required training components are installed.",
            RvcTrainingCheckLevel.READY,
        )
    return RvcTrainingCheck(
        "runtime",
        "Training Runtime",
        "{count} required runtime components are missing.",
        RvcTrainingCheckLevel.BLOCKER,
        (("count", len(inspection.missing_paths)),),
    )


def _storage_check(
    training_paths: tuple[Path, ...],
    workspace_root: Path,
    disk_usage: DiskUsage,
) -> RvcTrainingCheck:
    source_bytes = 0
    for path in training_paths:
        try:
            source_bytes += path.stat().st_size
        except OSError:
            continue
    required_bytes = estimate_rvc_training_required_bytes(source_bytes)
    try:
        available_bytes = max(0, int(disk_usage(workspace_root).free))
    except OSError:
        return RvcTrainingCheck(
            "storage",
            "Training Storage",
            "Available storage could not be checked.",
            RvcTrainingCheckLevel.WARNING,
        )
    values = (
        ("required", _format_gib(required_bytes)),
        ("available", _format_gib(available_bytes)),
    )
    if available_bytes < required_bytes:
        return RvcTrainingCheck(
            "storage",
            "Training Storage",
            "{required} GB required, {available} GB available.",
            RvcTrainingCheckLevel.BLOCKER,
            values,
        )
    return RvcTrainingCheck(
        "storage",
        "Training Storage",
        "{available} GB available; at least {required} GB reserved.",
        RvcTrainingCheckLevel.READY,
        values,
    )


def _device_check(
    backend: RvcComputeBackend,
    adapter_name: str,
    adapter_memory_bytes: int,
) -> RvcTrainingCheck:
    if backend in {RvcComputeBackend.CUDA, RvcComputeBackend.ROCM}:
        name = adapter_name or backend.value.upper()
        if adapter_memory_bytes > 0:
            return RvcTrainingCheck(
                "device",
                "Training Device",
                "{device} / {memory} GB VRAM",
                RvcTrainingCheckLevel.READY,
                (
                    ("device", name),
                    ("memory", _format_gib(adapter_memory_bytes)),
                ),
            )
        return RvcTrainingCheck(
            "device",
            "Training Device",
            "{device} acceleration is enabled.",
            RvcTrainingCheckLevel.READY,
            (("device", name),),
        )
    return RvcTrainingCheck(
        "device",
        "Training Device",
        "CPU training is available but will be significantly slower.",
        RvcTrainingCheckLevel.WARNING,
    )


def _format_gib(value: int) -> str:
    return f"{max(0, value) / 1024**3:.1f}"
