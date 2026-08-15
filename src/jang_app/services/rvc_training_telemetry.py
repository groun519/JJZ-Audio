from __future__ import annotations

import ctypes
import json
import os
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import Callable, Iterable, Sequence

from jang_app.services.command import CommandResult, run_command
from jang_app.services.rvc_hardware import RvcComputeBackend


_MIB = 1024**2


@dataclass(frozen=True)
class RvcTrainingTelemetrySnapshot:
    captured_at: str
    gpu_utilization_percent: float | None = None
    gpu_memory_used_bytes: int | None = None
    gpu_memory_total_bytes: int | None = None
    gpu_temperature_celsius: float | None = None
    cpu_utilization_percent: float | None = None
    system_memory_used_bytes: int | None = None
    system_memory_total_bytes: int | None = None
    monitor_error: str = ""

    @property
    def gpu_memory_percent(self) -> float | None:
        used = self.gpu_memory_used_bytes
        total = self.gpu_memory_total_bytes
        if used is None or total is None or total <= 0:
            return None
        return max(0.0, min(100.0, used * 100.0 / total))

    @property
    def system_memory_percent(self) -> float | None:
        used = self.system_memory_used_bytes
        total = self.system_memory_total_bytes
        if used is None or total is None or total <= 0:
            return None
        return max(0.0, min(100.0, used * 100.0 / total))

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, sort_keys=True)


class RvcTrainingHealth(StrEnum):
    WAITING = "waiting"
    STABLE = "stable"
    GPU_UNDERUSED = "gpu_underused"
    DATA_SUPPLY = "data_supply"
    MEMORY_PRESSURE = "memory_pressure"
    ACCELERATOR_UNAVAILABLE = "accelerator_unavailable"
    MONITOR_UNAVAILABLE = "monitor_unavailable"


@dataclass(frozen=True)
class RvcTrainingPerformanceAssessment:
    health: RvcTrainingHealth
    title: str
    detail: str


class RvcTrainingTelemetryHistory:
    def __init__(self, maximum_samples: int = 120) -> None:
        self._samples: deque[RvcTrainingTelemetrySnapshot] = deque(
            maxlen=max(5, int(maximum_samples))
        )

    @property
    def samples(self) -> tuple[RvcTrainingTelemetrySnapshot, ...]:
        return tuple(self._samples)

    def append(self, snapshot: RvcTrainingTelemetrySnapshot) -> None:
        self._samples.append(snapshot)

    def clear(self) -> None:
        self._samples.clear()


def assess_rvc_training_performance(
    samples: Iterable[RvcTrainingTelemetrySnapshot],
    backend: RvcComputeBackend,
) -> RvcTrainingPerformanceAssessment:
    history = tuple(samples)[-30:]
    if not history:
        return RvcTrainingPerformanceAssessment(
            RvcTrainingHealth.WAITING,
            "Waiting for training data",
            "Hardware usage will appear after training starts.",
        )
    latest = history[-1]
    if backend in {RvcComputeBackend.CUDA, RvcComputeBackend.ROCM}:
        gpu_values = _available(
            sample.gpu_utilization_percent for sample in history
        )
        if not gpu_values:
            if latest.monitor_error:
                return RvcTrainingPerformanceAssessment(
                    RvcTrainingHealth.MONITOR_UNAVAILABLE,
                    "GPU monitoring unavailable",
                    "Training continues normally; usage could not be measured.",
                )
            return RvcTrainingPerformanceAssessment(
                RvcTrainingHealth.ACCELERATOR_UNAVAILABLE,
                "GPU activity not detected",
                "Check the selected training device and runtime profile.",
            )
        memory_values = _available(sample.gpu_memory_percent for sample in history)
        average_gpu = fmean(gpu_values)
        average_memory = fmean(memory_values) if memory_values else 0.0
        if average_memory >= 92.0:
            return RvcTrainingPerformanceAssessment(
                RvcTrainingHealth.MEMORY_PRESSURE,
                "GPU memory is nearly full",
                "Reduce the batch size if training becomes unstable.",
            )
        cpu_values = _available(sample.cpu_utilization_percent for sample in history)
        average_cpu = fmean(cpu_values) if cpu_values else 0.0
        if len(gpu_values) >= 5 and average_gpu < 45.0 and average_cpu >= 70.0:
            return RvcTrainingPerformanceAssessment(
                RvcTrainingHealth.DATA_SUPPLY,
                "Data supply may be limiting the GPU",
                "Compare additional data-loader workers after this run.",
            )
        if len(gpu_values) >= 5 and average_gpu < 45.0:
            return RvcTrainingPerformanceAssessment(
                RvcTrainingHealth.GPU_UNDERUSED,
                "GPU usage is lower than expected",
                "The current stage may be CPU-bound or waiting for data.",
            )
        detail = "GPU usage is stable."
        if average_gpu >= 70.0 and average_memory < 65.0:
            detail = "GPU usage is stable and VRAM headroom remains for a batch benchmark."
        return RvcTrainingPerformanceAssessment(
            RvcTrainingHealth.STABLE,
            "Training performance is stable",
            detail,
        )
    return RvcTrainingPerformanceAssessment(
        RvcTrainingHealth.STABLE,
        "CPU training is running",
        "CPU training is supported but will take longer than GPU training.",
    )


NvidiaRunner = Callable[[Sequence[str]], CommandResult]


class RvcTrainingTelemetryProbe:
    def __init__(
        self,
        backend: RvcComputeBackend,
        *,
        nvidia_runner: NvidiaRunner | None = None,
    ) -> None:
        self._backend = backend
        self._nvidia_runner = nvidia_runner or _run_nvidia_smi
        self._previous_cpu_times: tuple[int, int] | None = None

    def sample(self) -> RvcTrainingTelemetrySnapshot:
        cpu_percent = self._sample_cpu_percent()
        memory_used, memory_total = _sample_system_memory()
        gpu_utilization: float | None = None
        gpu_memory_used: int | None = None
        gpu_memory_total: int | None = None
        gpu_temperature: float | None = None
        monitor_error = ""
        if self._backend == RvcComputeBackend.CUDA:
            try:
                result = self._nvidia_runner(
                    (
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    )
                )
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout).strip())
                (
                    gpu_utilization,
                    gpu_memory_used,
                    gpu_memory_total,
                    gpu_temperature,
                ) = parse_nvidia_smi_telemetry(result.stdout)
            except (OSError, RuntimeError, ValueError) as exc:
                monitor_error = str(exc).strip() or "NVIDIA telemetry query failed."
        elif self._backend == RvcComputeBackend.ROCM:
            monitor_error = "ROCm GPU usage monitoring is not available on this system."
        return RvcTrainingTelemetrySnapshot(
            captured_at=datetime.now(UTC).isoformat(),
            gpu_utilization_percent=gpu_utilization,
            gpu_memory_used_bytes=gpu_memory_used,
            gpu_memory_total_bytes=gpu_memory_total,
            gpu_temperature_celsius=gpu_temperature,
            cpu_utilization_percent=cpu_percent,
            system_memory_used_bytes=memory_used,
            system_memory_total_bytes=memory_total,
            monitor_error=monitor_error,
        )

    def _sample_cpu_percent(self) -> float | None:
        current = _read_windows_cpu_times()
        previous = self._previous_cpu_times
        self._previous_cpu_times = current
        if current is None or previous is None:
            return None
        idle_delta = current[0] - previous[0]
        total_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def parse_nvidia_smi_telemetry(
    output: str,
) -> tuple[float, int, int, float | None]:
    line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        raise ValueError("NVIDIA telemetry returned an invalid response.")
    utilization = max(0.0, min(100.0, float(parts[0])))
    used = max(0, round(float(parts[1]) * _MIB))
    total = max(0, round(float(parts[2]) * _MIB))
    temperature = None
    if len(parts) > 3 and parts[3] not in {"", "N/A", "[N/A]"}:
        temperature = float(parts[3])
    return utilization, used, total, temperature


def append_telemetry_snapshot(
    folder: Path | None,
    snapshot: RvcTrainingTelemetrySnapshot,
) -> None:
    if folder is None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "telemetry.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(snapshot.as_json())
            stream.write("\n")
    except OSError:
        return


def _available(values: Iterable[float | None]) -> tuple[float, ...]:
    return tuple(float(value) for value in values if value is not None)


def _run_nvidia_smi(args: Sequence[str]) -> CommandResult:
    return run_command(list(args), timeout_seconds=3.0)


if os.name == "nt":
    from ctypes import wintypes

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = (
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )


def _sample_system_memory() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    total = int(status.ullTotalPhys)
    available = int(status.ullAvailPhys)
    return max(0, total - available), max(0, total)


def _read_windows_cpu_times() -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    idle = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return None
    idle_value = _filetime_value(idle)
    kernel_value = _filetime_value(kernel)
    user_value = _filetime_value(user)
    return idle_value, kernel_value + user_value


def _filetime_value(value: object) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
