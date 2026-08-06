from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.runtime_installation import installed_rvc_runtime_profile
from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    RvcComputeBackend,
    RvcHardwareSelection,
    RvcSupportLevel,
)
from jang_app.services.rvc_runtime_profile import detect_rvc_hardware
from jang_app.services.system_diagnostics import SystemDiagnostics


HARDWARE_DIAGNOSTICS_SCHEMA_VERSION = 1
HARDWARE_DIAGNOSTICS_FILE_NAME = "hardware_diagnostics.json"
HARDWARE_RECHECK_INTERVAL = timedelta(days=7)


def hardware_diagnostics_file(paths: AppPaths) -> Path:
    return paths.settings_dir / HARDWARE_DIAGNOSTICS_FILE_NAME


def recorded_hardware_profile(paths: AppPaths) -> str:
    data = _load_hardware_diagnostics(paths)
    return _profile_from_data(data)


def recorded_hardware_selection(
    paths: AppPaths,
) -> RvcHardwareSelection | None:
    data = _load_hardware_diagnostics(paths)
    if data is None:
        return None
    profile = _profile_from_data(data)
    if not profile:
        return None
    adapter_name = _text(data.get("adapter_name"))
    adapter = (
        GraphicsAdapter(
            adapter_name,
            _text(data.get("adapter_vendor")),
            _text(data.get("adapter_pnp_device_id")),
            _text(data.get("adapter_driver_version")),
            _nonnegative_int(data.get("adapter_ram")),
        )
        if adapter_name
        else None
    )
    backend, training_backend, support_level = _profile_capabilities(profile)
    return RvcHardwareSelection(
        profile,
        backend,
        support_level,
        adapter,
        training_backend,
        _text(data.get("hardware_reason")),
    )


def _load_hardware_diagnostics(paths: AppPaths) -> dict[str, object] | None:
    try:
        data = json.loads(hardware_diagnostics_file(paths).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != HARDWARE_DIAGNOSTICS_SCHEMA_VERSION:
        return None
    return data


def _profile_from_data(data: dict[str, object] | None) -> str:
    if data is None:
        return ""
    profile = data.get("active_profile") or data.get("desired_profile")
    return profile.strip() if isinstance(profile, str) else ""


def hardware_diagnostics_required(
    paths: AppPaths,
    *,
    selection: RvcHardwareSelection | None = None,
) -> bool:
    try:
        data = json.loads(hardware_diagnostics_file(paths).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict) or data.get("schema_version") != HARDWARE_DIAGNOSTICS_SCHEMA_VERSION:
        return True
    installed = installed_rvc_runtime_profile(paths.runtime_root / "rvc")
    if data.get("installed_profile") != (installed.profile if installed is not None else ""):
        return True
    if data.get("installed_profile_version") != (installed.version if installed is not None else ""):
        return True
    if selection is None and _checked_recently(data.get("checked_at")):
        return False
    expected = _signature(paths, selection or detect_rvc_hardware())
    return not isinstance(data, dict) or any(
        data.get(key) != value for key, value in expected.items()
    )


def record_hardware_diagnostics(
    paths: AppPaths,
    diagnostics: SystemDiagnostics,
    *,
    selection: RvcHardwareSelection | None = None,
) -> Path:
    current = selection or detect_rvc_hardware()
    payload = {
        **_signature(paths, current),
        "checked_at": datetime.now(UTC).isoformat(),
        "ready": diagnostics.ready,
        "warning_count": sum(check.status == "warning" for check in diagnostics.checks),
        "failed_checks": [check.key for check in diagnostics.checks if check.status == "fail"],
    }
    target = hardware_diagnostics_file(paths)
    write_json_atomic(target, payload)
    return target


def _signature(paths: AppPaths, selection: RvcHardwareSelection) -> dict[str, object]:
    installed = installed_rvc_runtime_profile(paths.runtime_root / "rvc")
    active_profile = (
        installed.profile
        if installed is not None and installed.activation_status == "fallback"
        else selection.profile
    )
    adapter = selection.adapter
    return {
        "schema_version": HARDWARE_DIAGNOSTICS_SCHEMA_VERSION,
        "hardware_fingerprint": selection.fingerprint,
        "desired_profile": selection.profile,
        "active_profile": active_profile,
        "backend": selection.backend.value,
        "training_backend": selection.training_backend.value,
        "support_level": selection.support_level.value,
        "hardware_reason": selection.reason,
        "adapter_name": adapter.name if adapter is not None else "",
        "adapter_vendor": adapter.vendor if adapter is not None else "",
        "adapter_pnp_device_id": adapter.pnp_device_id if adapter is not None else "",
        "adapter_driver_version": adapter.driver_version if adapter is not None else "",
        "adapter_ram": adapter.adapter_ram if adapter is not None else 0,
        "installed_profile": installed.profile if installed is not None else "",
        "installed_profile_version": installed.version if installed is not None else "",
    }


def _profile_capabilities(
    profile: str,
) -> tuple[RvcComputeBackend, RvcComputeBackend, RvcSupportLevel]:
    if profile.startswith("cu"):
        return (
            RvcComputeBackend.CUDA,
            RvcComputeBackend.CUDA,
            RvcSupportLevel.FULL_GPU,
        )
    if profile == "rocm-win":
        return (
            RvcComputeBackend.ROCM,
            RvcComputeBackend.ROCM,
            RvcSupportLevel.FULL_GPU,
        )
    if profile == "directml":
        return (
            RvcComputeBackend.DIRECTML,
            RvcComputeBackend.CPU,
            RvcSupportLevel.INFERENCE_GPU,
        )
    return (
        RvcComputeBackend.CPU,
        RvcComputeBackend.CPU,
        RvcSupportLevel.CPU,
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _checked_recently(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        checked = datetime.fromisoformat(value)
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return datetime.now(UTC) - checked.astimezone(UTC) < HARDWARE_RECHECK_INTERVAL
