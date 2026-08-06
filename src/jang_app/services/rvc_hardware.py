from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

from jang_app.services.command import hidden_subprocess_kwargs


class RvcComputeBackend(StrEnum):
    CUDA = "cuda"
    ROCM = "rocm"
    DIRECTML = "directml"
    CPU = "cpu"


class RvcSupportLevel(StrEnum):
    FULL_GPU = "full_gpu"
    INFERENCE_GPU = "inference_gpu"
    CPU = "cpu"


@dataclass(frozen=True)
class GraphicsAdapter:
    name: str
    vendor: str
    pnp_device_id: str = ""
    driver_version: str = ""
    adapter_ram: int = 0


@dataclass(frozen=True)
class RvcHardwareSelection:
    profile: str
    backend: RvcComputeBackend
    support_level: RvcSupportLevel
    adapter: GraphicsAdapter | None = None
    training_backend: RvcComputeBackend = RvcComputeBackend.CPU
    reason: str = ""

    @property
    def inference_accelerated(self) -> bool:
        return self.backend != RvcComputeBackend.CPU

    @property
    def training_accelerated(self) -> bool:
        return self.training_backend in {RvcComputeBackend.CUDA, RvcComputeBackend.ROCM}

    @property
    def fingerprint(self) -> str:
        adapter = self.adapter
        payload = {
            "profile": self.profile,
            "backend": self.backend.value,
            "training_backend": self.training_backend.value,
            "name": adapter.name if adapter is not None else "",
            "vendor": adapter.vendor if adapter is not None else "",
            "pnp_device_id": adapter.pnp_device_id if adapter is not None else "",
            "driver_version": adapter.driver_version if adapter is not None else "",
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]


class CommandResultLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


GraphicsCommandRunner = Callable[[Sequence[str]], CommandResultLike]

_LOGGER = logging.getLogger("jang_app")
_AMD_ROCM_WINDOWS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bRadeon\s+RX\s+9070\s+XT\b",
        r"\bRadeon\s+RX\s+9070\b",
        r"\bRadeon\s+AI\s+PRO\s+R9700\b",
        r"\bRadeon\s+RX\s+9060\s+XT\b",
        r"\bRadeon\s+RX\s+7900\s+XTX\b",
        r"\bRadeon\s+PRO\s+W7900(?:\s+Dual\s+Slot)?\b",
        r"\bRadeon\s+RX\s+7700\b",
    )
)


def detect_rvc_hardware_selection(
    nvidia_gpus: Sequence[object] = (),
) -> RvcHardwareSelection:
    return select_rvc_hardware(detect_graphics_adapters(), nvidia_gpus=nvidia_gpus)


def select_rvc_hardware(
    adapters: Sequence[GraphicsAdapter],
    *,
    nvidia_gpus: Sequence[object] = (),
) -> RvcHardwareSelection:
    nvidia = next((adapter for adapter in adapters if adapter.vendor == "nvidia"), None)
    if nvidia is not None or nvidia_gpus:
        gpu = nvidia_gpus[0] if nvidia_gpus else None
        name = str(getattr(gpu, "name", "")).strip() or (
            nvidia.name if nvidia is not None else "NVIDIA GPU"
        )
        capability = tuple(getattr(gpu, "compute_capability", ()) or ())
        is_blackwell = bool(getattr(gpu, "is_blackwell", False)) or capability >= (12, 0)
        if not is_blackwell:
            is_blackwell = bool(re.search(r"\bRTX\s*50\d{2}\b", name, re.IGNORECASE))
        adapter = nvidia or GraphicsAdapter(name, "nvidia")
        memory_bytes = max(0, int(getattr(gpu, "memory_bytes", 0) or 0))
        if memory_bytes:
            adapter = replace(adapter, name=name, adapter_ram=memory_bytes)
        return RvcHardwareSelection(
            "cu128" if is_blackwell else "cu118",
            RvcComputeBackend.CUDA,
            RvcSupportLevel.FULL_GPU,
            adapter,
            RvcComputeBackend.CUDA,
            "NVIDIA CUDA runtime selected.",
        )

    amd_adapters = tuple(adapter for adapter in adapters if adapter.vendor == "amd")
    amd = next(
        (adapter for adapter in amd_adapters if is_windows_rocm_supported(adapter.name)),
        amd_adapters[0] if amd_adapters else None,
    )
    if amd is not None and is_windows_rocm_supported(amd.name):
        return RvcHardwareSelection(
            "rocm-win",
            RvcComputeBackend.ROCM,
            RvcSupportLevel.FULL_GPU,
            amd,
            RvcComputeBackend.ROCM,
            "AMD Windows ROCm candidate selected; activation requires a GPU forward probe.",
        )
    if amd is not None:
        return RvcHardwareSelection(
            "directml",
            RvcComputeBackend.DIRECTML,
            RvcSupportLevel.INFERENCE_GPU,
            amd,
            RvcComputeBackend.CPU,
            "DirectML inference selected; model training uses CPU.",
        )
    return RvcHardwareSelection(
        "cpu",
        RvcComputeBackend.CPU,
        RvcSupportLevel.CPU,
        reason="No supported GPU adapter was detected.",
    )


def is_windows_rocm_supported(name: str) -> bool:
    return any(pattern.search(name) for pattern in _AMD_ROCM_WINDOWS_PATTERNS)


def detect_graphics_adapters() -> tuple[GraphicsAdapter, ...]:
    return _detect_graphics_adapters_cached()


def clear_graphics_adapter_cache() -> None:
    _detect_graphics_adapters_cached.cache_clear()


@lru_cache(maxsize=1)
def _detect_graphics_adapters_cached() -> tuple[GraphicsAdapter, ...]:
    return probe_graphics_adapters()


def probe_graphics_adapters(
    command_runner: GraphicsCommandRunner | None = None,
) -> tuple[GraphicsAdapter, ...]:
    runner = command_runner or _run_powershell
    result = runner(
        (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,PNPDeviceID,DriverVersion,AdapterRAM | "
            "ConvertTo-Json -Compress",
        )
    )
    if result.returncode != 0 or not result.stdout.strip():
        _LOGGER.warning("GPU adapter detection failed: %s", result.stderr.strip())
        return ()
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        _LOGGER.warning("GPU adapter detection returned invalid JSON: %s", exc)
        return ()
    rows = raw if isinstance(raw, list) else [raw]
    return tuple(
        adapter
        for row in rows
        if isinstance(row, dict) and (adapter := _adapter_from_row(row)) is not None
    )


def _adapter_from_row(row: dict[str, object]) -> GraphicsAdapter | None:
    name = str(row.get("Name") or "").strip()
    if not name:
        return None
    folded = name.casefold()
    pnp = str(row.get("PNPDeviceID") or "").strip()
    if "nvidia" in folded or "ven_10de" in pnp.casefold():
        vendor = "nvidia"
    elif any(token in folded for token in ("amd", "radeon")) or "ven_1002" in pnp.casefold():
        vendor = "amd"
    elif "intel" in folded or "ven_8086" in pnp.casefold():
        vendor = "intel"
    else:
        vendor = "other"
    try:
        ram = max(0, int(row.get("AdapterRAM") or 0))
    except (TypeError, ValueError):
        ram = 0
    return GraphicsAdapter(
        name=name,
        vendor=vendor,
        pnp_device_id=pnp,
        driver_version=str(row.get("DriverVersion") or "").strip(),
        adapter_ram=ram,
    )


def _run_powershell(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(args), 1, "", str(exc))
