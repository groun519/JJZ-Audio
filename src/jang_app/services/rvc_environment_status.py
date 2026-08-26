from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.hardware_diagnostics_state import recorded_hardware_selection
from jang_app.services.runtime_installation import installed_rvc_runtime_profile
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_runtime_profile import detect_rvc_hardware
from jang_app.services.rvc_training_runtime import inspect_rvc_training_runtime


@dataclass(frozen=True)
class RvcEnvironmentCheck:
    key: str
    title: str
    status: str
    detail: str


@dataclass(frozen=True)
class RvcEnvironmentSnapshot:
    status: str
    summary: str
    root: Path
    installation_kind: str
    active_profile: str
    preferred_profile: str
    runtime_version: str
    python_version: str
    torch_version: str
    cuda_version: str
    hip_version: str
    capability: tuple[int, int]
    inference_backend: str
    training_backend: str
    adapter_name: str
    activation_status: str
    checks: tuple[RvcEnvironmentCheck, ...]
    checked_at: datetime
    deep_checked: bool


def collect_rvc_environment_status(
    paths: AppPaths,
    *,
    deep: bool = False,
) -> RvcEnvironmentSnapshot:
    root = (paths.runtime_root / "rvc").resolve()
    installed = installed_rvc_runtime_profile(root)
    selection = recorded_hardware_selection(paths) or detect_rvc_hardware()
    inspection = inspect_rvc_training_runtime(root, check_cuda=deep)
    adapter = selection.adapter
    managed = installed is not None
    installation_kind = "Managed installation" if managed else "Existing installation"
    profile = installed.profile if installed is not None else selection.profile
    preferred = installed.preferred_profile if installed is not None else selection.profile
    activation = installed.activation_status if installed is not None else "legacy"

    checks = _environment_checks(
        root,
        inspection,
        managed=managed,
        deep=deep,
        expected_backend=selection.training_backend,
    )
    if not inspection.assets_ready:
        status = "failed"
        summary = "The RVC runtime is incomplete and needs repair."
    elif deep and inspection.cuda_error and selection.training_accelerated:
        status = "failed"
        summary = "The selected GPU runtime failed its execution check."
    elif deep and selection.training_accelerated and not inspection.training_accelerated:
        status = "warning"
        summary = "RVC can run, but GPU training acceleration is unavailable."
    elif installed is None:
        status = "completed"
        summary = "RVC is ready using an existing installation."
    elif installed.activation_status == "fallback":
        status = "warning"
        summary = "RVC is using a fallback runtime profile."
    else:
        status = "completed"
        summary = "RVC is ready for conversion and model training."

    return RvcEnvironmentSnapshot(
        status=status,
        summary=summary,
        root=root,
        installation_kind=installation_kind,
        active_profile=profile,
        preferred_profile=preferred,
        runtime_version=installed.version if installed is not None else "",
        python_version=inspection.python_version,
        torch_version=inspection.torch_version,
        cuda_version=inspection.cuda_version,
        hip_version=inspection.hip_version,
        capability=inspection.device_capability,
        inference_backend=selection.backend.value,
        training_backend=selection.training_backend.value,
        adapter_name=adapter.name if adapter is not None else "CPU",
        activation_status=activation,
        checks=checks,
        checked_at=datetime.now(UTC),
        deep_checked=deep,
    )


def _environment_checks(
    root: Path,
    inspection,
    *,
    managed: bool,
    deep: bool,
    expected_backend: RvcComputeBackend,
) -> tuple[RvcEnvironmentCheck, ...]:
    runtime_ready = (root / "runtime" / "python.exe").is_file()
    missing_detail = (
        ", ".join(str(path) for path in inspection.missing_paths[:3])
        if inspection.missing_paths
        else "All required RVC files were found."
    )
    if len(inspection.missing_paths) > 3:
        missing_detail += f" and {len(inspection.missing_paths) - 3} more"
    cpu_status = (
        "completed"
        if inspection.cpu_ready is True
        else "failed"
        if inspection.cpu_ready is False
        else "pending"
    )
    if not deep:
        accelerator_status = "pending"
        accelerator_detail = "Run the detailed check to test the installed runtime."
    elif expected_backend in {RvcComputeBackend.CUDA, RvcComputeBackend.ROCM}:
        accelerator_status = "completed" if inspection.training_accelerated else "failed"
        accelerator_detail = inspection.cuda_error or (
            f"{inspection.cuda_device_count} accelerated device(s) are available."
            if inspection.training_accelerated
            else "The installed runtime did not expose an accelerated training device."
        )
    else:
        accelerator_status = "completed"
        accelerator_detail = f"The selected training backend is {expected_backend.value.upper()}."
    return (
        RvcEnvironmentCheck(
            "runtime",
            "Runtime executable",
            "completed" if runtime_ready else "failed",
            str(root / "runtime" / "python.exe"),
        ),
        RvcEnvironmentCheck(
            "assets",
            "Required RVC files",
            "completed" if inspection.assets_ready else "failed",
            missing_detail,
        ),
        RvcEnvironmentCheck(
            "metadata",
            "Managed profile information",
            "completed" if managed else "info",
            "The installed profile can be updated and repaired automatically."
            if managed
            else "This existing runtime works, but automatic repair information is limited.",
        ),
        RvcEnvironmentCheck(
            "cpu",
            "Runtime execution",
            cpu_status,
            "The runtime executed a tensor operation successfully."
            if inspection.cpu_ready is True
            else "Run the detailed check to execute the runtime."
            if inspection.cpu_ready is None
            else "The runtime could not execute its CPU validation operation.",
        ),
        RvcEnvironmentCheck(
            "accelerator",
            "Training acceleration",
            accelerator_status,
            accelerator_detail,
        ),
    )
