from __future__ import annotations

import ctypes
import json
import os
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.hardware_diagnostics_state import recorded_hardware_selection
from jang_app.services.rvc_hardware import (
    GraphicsAdapter,
    clear_graphics_adapter_cache,
    detect_graphics_adapters,
    select_rvc_hardware,
)


@dataclass(frozen=True)
class ProcessorInformation:
    name: str
    physical_cores: int
    logical_processors: int
    architecture: str


@dataclass(frozen=True)
class MemoryInformation:
    total_bytes: int
    available_bytes: int

    @property
    def used_bytes(self) -> int:
        return max(0, self.total_bytes - self.available_bytes)

    @property
    def used_percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return max(0, min(100, round(self.used_bytes * 100 / self.total_bytes)))


@dataclass(frozen=True)
class PcEnvironmentSnapshot:
    os_description: str
    processor: ProcessorInformation
    memory: MemoryInformation
    adapters: tuple[GraphicsAdapter, ...]
    selected_adapter_name: str
    selected_profile: str
    checked_at: datetime
    warnings: tuple[str, ...] = ()


def collect_pc_environment(
    paths: AppPaths,
    *,
    refresh_hardware: bool = False,
) -> PcEnvironmentSnapshot:
    warnings: list[str] = []
    if refresh_hardware:
        clear_graphics_adapter_cache()
    try:
        adapters = detect_graphics_adapters()
    except Exception as exc:  # Hardware providers are optional on older Windows builds.
        adapters = ()
        warnings.append(str(exc).strip() or "Graphics adapters could not be read.")

    recorded = recorded_hardware_selection(paths)
    selected = recorded or select_rvc_hardware(adapters)
    selected_adapter = selected.adapter
    processor = _processor_information()
    memory = _memory_information()
    if memory.total_bytes <= 0:
        warnings.append("System memory information is unavailable.")
    return PcEnvironmentSnapshot(
        os_description=platform.platform(),
        processor=processor,
        memory=memory,
        adapters=adapters,
        selected_adapter_name=(selected_adapter.name if selected_adapter else ""),
        selected_profile=selected.profile,
        checked_at=datetime.now(UTC),
        warnings=tuple(warnings),
    )


def _processor_information() -> ProcessorInformation:
    fallback_name = platform.processor().strip() or platform.machine().strip() or "Unknown CPU"
    logical = max(0, int(os.cpu_count() or 0))
    if platform.system() != "Windows":
        return ProcessorInformation(fallback_name, 0, logical, platform.machine())
    try:
        from jang_app.services.command import run_command

        result = run_command(
            (
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Processor | "
                "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | "
                "ConvertTo-Json -Compress",
            )
        )
        if result.returncode == 0 and result.stdout.strip():
            values = json.loads(result.stdout.strip())
            records = values if isinstance(values, list) else [values]
            names = tuple(
                str(item.get("Name", "")).strip()
                for item in records
                if isinstance(item, dict) and str(item.get("Name", "")).strip()
            )
            physical = sum(
                max(0, int(item.get("NumberOfCores", 0) or 0))
                for item in records
                if isinstance(item, dict)
            )
            detected_logical = sum(
                max(0, int(item.get("NumberOfLogicalProcessors", 0) or 0))
                for item in records
                if isinstance(item, dict)
            )
            return ProcessorInformation(
                " / ".join(dict.fromkeys(names)) or fallback_name,
                physical,
                detected_logical or logical,
                platform.machine(),
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return ProcessorInformation(fallback_name, 0, logical, platform.machine())


def _memory_information() -> MemoryInformation:
    if platform.system() == "Windows":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = (
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            )

        state = MemoryStatusEx()
        state.length = ctypes.sizeof(MemoryStatusEx)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return MemoryInformation(
                    int(state.total_physical),
                    int(state.available_physical),
                )
        except (AttributeError, OSError):
            pass
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
        available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        return MemoryInformation(total, available)
    except (AttributeError, OSError, TypeError, ValueError):
        return MemoryInformation(0, 0)
