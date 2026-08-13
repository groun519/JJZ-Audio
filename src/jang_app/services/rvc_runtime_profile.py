from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, Sequence

from jang_app.services.command import CommandResult, run_command
from jang_app.services.rvc_hardware import (
    RvcHardwareSelection,
    clear_graphics_adapter_cache,
    detect_rvc_hardware_selection as detect_hardware_selection,
)


RVC_PROFILE_CU118 = "cu118"
RVC_PROFILE_CU128 = "cu128"
RVC_PROFILE_DIRECTML = "directml"
RVC_PROFILE_ROCM_WINDOWS = "rocm-win"
RVC_PROFILE_CPU = "cpu"
RVC_PROFILE_COMPONENT_PREFIX = "rvc-runtime-"
DEFAULT_RVC_PROFILE = RVC_PROFILE_CU118
RVC_RUNTIME_PROFILES = (
    RVC_PROFILE_CU118,
    RVC_PROFILE_CU128,
    RVC_PROFILE_DIRECTML,
    RVC_PROFILE_ROCM_WINDOWS,
    RVC_PROFILE_CPU,
)
RVC_BASE_RUNTIME_PROFILES = (RVC_PROFILE_CU118, RVC_PROFILE_CPU)
_LOGGER = logging.getLogger("jang_app")


class CommandResultLike(Protocol):
    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


GpuCommandRunner = Callable[[Sequence[str]], CommandResultLike]


@dataclass(frozen=True)
class NvidiaGpu:
    name: str
    compute_capability: tuple[int, int] = ()
    memory_bytes: int = 0

    @property
    def is_blackwell(self) -> bool:
        return self.compute_capability >= (12, 0) or bool(
            re.search(r"\bRTX\s*50\d{2}\b", self.name, re.IGNORECASE)
        ) or "blackwell" in self.name.casefold()


def rvc_profile_component_id(profile: str) -> str:
    normalized = normalize_rvc_profile(profile)
    return f"{RVC_PROFILE_COMPONENT_PREFIX}{normalized}"


def rvc_profile_requires_overlay(profile: str) -> bool:
    return normalize_rvc_profile(profile) not in RVC_BASE_RUNTIME_PROFILES


def rvc_profile_candidates(profile: object) -> tuple[str, ...]:
    preferred = normalize_rvc_profile(profile)
    if preferred == RVC_PROFILE_ROCM_WINDOWS:
        return (RVC_PROFILE_ROCM_WINDOWS, RVC_PROFILE_DIRECTML, RVC_PROFILE_CPU)
    if preferred == RVC_PROFILE_DIRECTML:
        return (RVC_PROFILE_DIRECTML, RVC_PROFILE_CPU)
    if preferred == RVC_PROFILE_CU128:
        return (RVC_PROFILE_CU128, RVC_PROFILE_CPU)
    if preferred == RVC_PROFILE_CU118:
        return (RVC_PROFILE_CU118, RVC_PROFILE_CPU)
    # The cu118 build is also the validated CPU fallback. New releases package
    # it separately, while legacy releases continue to fall back to the base runtime.
    return (RVC_PROFILE_CU118, RVC_PROFILE_CPU)


def normalize_rvc_profile(profile: object) -> str:
    value = str(profile or "").strip().lower()
    return value if value in RVC_RUNTIME_PROFILES else DEFAULT_RVC_PROFILE


def select_rvc_runtime_profile(gpus: Sequence[NvidiaGpu]) -> str:
    return RVC_PROFILE_CU128 if any(gpu.is_blackwell for gpu in gpus) else RVC_PROFILE_CU118


def detect_rvc_runtime_profile() -> str:
    selection = detect_rvc_hardware()
    _LOGGER.info(
        "RVC hardware profile | adapter=%s | backend=%s | training=%s | selected=%s | reason=%s",
        selection.adapter.name if selection.adapter is not None else "none",
        selection.backend.value,
        selection.training_backend.value,
        selection.profile,
        selection.reason,
    )
    return selection.profile


def detect_rvc_hardware() -> RvcHardwareSelection:
    return detect_hardware_selection(detect_nvidia_gpus())


def detect_nvidia_gpus() -> tuple[NvidiaGpu, ...]:
    return _detect_nvidia_gpus_cached()


def clear_nvidia_gpu_cache() -> None:
    _detect_nvidia_gpus_cached.cache_clear()
    clear_graphics_adapter_cache()


@lru_cache(maxsize=1)
def _detect_nvidia_gpus_cached() -> tuple[NvidiaGpu, ...]:
    return probe_nvidia_gpus()


def probe_nvidia_gpus(command_runner: GpuCommandRunner | None = None) -> tuple[NvidiaGpu, ...]:
    runner = command_runner or _run_nvidia_smi
    result = runner(
        (
            "nvidia-smi",
            "--query-gpu=name,compute_cap,memory.total",
            "--format=csv,noheader,nounits",
        )
    )
    if result.returncode == 0:
        parsed = _parse_gpu_rows(
            result.stdout,
            with_capability=True,
            with_memory=True,
        )
        if parsed:
            return parsed

    fallback = runner(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        )
    )
    return (
        _parse_gpu_rows(
            fallback.stdout,
            with_capability=False,
            with_memory=True,
        )
        if fallback.returncode == 0
        else ()
    )


def _run_nvidia_smi(args: Sequence[str]) -> CommandResult:
    return run_command(args, timeout_seconds=15)


def _parse_gpu_rows(
    output: str,
    *,
    with_capability: bool,
    with_memory: bool,
) -> tuple[NvidiaGpu, ...]:
    gpus: list[NvidiaGpu] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        minimum_parts = 1 + int(with_capability) + int(with_memory)
        if len(parts) < minimum_parts:
            if len(parts) == 1:
                gpus.append(NvidiaGpu(parts[0]))
            elif with_capability and len(parts) == 2:
                gpus.append(NvidiaGpu(parts[0], _parse_capability(parts[1])))
            continue
        name = ",".join(parts[: len(parts) - int(with_capability) - int(with_memory)])
        offset = len(parts) - int(with_capability) - int(with_memory)
        capability = _parse_capability(parts[offset]) if with_capability else ()
        memory_mib = _parse_memory_mib(parts[-1]) if with_memory else 0
        gpus.append(NvidiaGpu(name.strip(), capability, memory_mib * 1024**2))
    return tuple(gpus)


def _parse_capability(value: str) -> tuple[int, int]:
    match = re.search(r"(?P<major>\d+)\.(?P<minor>\d+)", value)
    if match is None:
        return ()
    return int(match.group("major")), int(match.group("minor"))


def _parse_memory_mib(value: str) -> int:
    match = re.search(r"\d+", value)
    return int(match.group()) if match is not None else 0
