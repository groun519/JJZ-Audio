from __future__ import annotations

import ctypes
import os


APP_MUTEX_NAME = "JJZeroAudio.E5ED303D5BB24B1E8AA8434C16C4D3AE"


def create_app_mutex() -> int | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    return int(handle) if handle else None


def close_app_mutex(handle: int | None) -> bool:
    if os.name != "nt" or not handle:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    return bool(kernel32.CloseHandle(handle))
