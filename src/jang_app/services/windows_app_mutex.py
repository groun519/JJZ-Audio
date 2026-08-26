from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


APP_MUTEX_NAME = "JJZeroAudio.E5ED303D5BB24B1E8AA8434C16C4D3AE"
ERROR_ALREADY_EXISTS = 183


@dataclass(frozen=True)
class AppMutexAcquisition:
    handle: int | None
    already_running: bool


def acquire_app_mutex() -> AppMutexAcquisition:
    if os.name != "nt":
        return AppMutexAcquisition(None, False)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    raw_handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    error = ctypes.get_last_error()
    handle = int(raw_handle) if raw_handle else None
    if handle and error == ERROR_ALREADY_EXISTS:
        close_app_mutex(handle)
        return AppMutexAcquisition(None, True)
    return AppMutexAcquisition(handle, False)


def create_app_mutex() -> int | None:
    """Compatibility wrapper for callers that only need the acquired handle."""

    return acquire_app_mutex().handle


def close_app_mutex(handle: int | None) -> bool:
    if os.name != "nt" or not handle:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    return bool(kernel32.CloseHandle(handle))
