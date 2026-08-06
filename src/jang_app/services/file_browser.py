from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

from jang_app.services.app_logging import get_logger


def open_in_file_browser(path: Path) -> Path:
    target = path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {target}")

    logger = get_logger()
    target_kind = "directory" if target.is_dir() else "file"
    logger.info("Opening %s in file browser: %s", target_kind, target)
    if sys.platform == "win32":
        try:
            _open_windows_shell(target)
        except OSError as exc:
            logger.warning("Windows Shell API failed for %s; using Explorer fallback: %s", target, exc)
            _open_windows_explorer_fallback(target)
    else:
        subprocess.Popen(["open", str(target if target.is_dir() else target.parent)])
    return target


def _open_windows_shell(target: Path) -> None:
    shell32 = ctypes.windll.shell32
    if target.is_dir():
        shell_execute = shell32.ShellExecuteW
        shell_execute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        shell_execute.restype = ctypes.c_void_p
        result = shell_execute(None, "open", str(target), None, None, 1)
        result_code = int(result or 0)
        if result_code <= 32:
            raise OSError(result_code, f"ShellExecuteW could not open directory: {target}")
        return

    ole32 = ctypes.windll.ole32
    co_initialize = ole32.CoInitializeEx
    co_initialize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    co_initialize.restype = ctypes.c_long
    co_result = co_initialize(None, 0x2)
    rpc_changed_mode = ctypes.c_int32(0x80010106).value
    if co_result < 0 and co_result != rpc_changed_mode:
        raise OSError(co_result, "Could not initialize Windows Shell integration.")
    should_uninitialize = co_result in {0, 1}

    create_pidl = shell32.ILCreateFromPathW
    create_pidl.argtypes = [ctypes.c_wchar_p]
    create_pidl.restype = ctypes.c_void_p
    select_item = shell32.SHOpenFolderAndSelectItems
    select_item.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
    select_item.restype = ctypes.c_long
    free_pidl = shell32.ILFree
    free_pidl.argtypes = [ctypes.c_void_p]
    free_pidl.restype = None
    co_uninitialize = ole32.CoUninitialize
    co_uninitialize.argtypes = []
    co_uninitialize.restype = None
    pidl = None
    try:
        pidl = create_pidl(str(target))
        if not pidl:
            raise OSError(f"Could not resolve a Windows Shell item for: {target}")
        result = select_item(pidl, 0, None, 0)
        if result < 0:
            raise OSError(result, f"Windows Shell could not select file: {target}")
    finally:
        if pidl:
            free_pidl(pidl)
        if should_uninitialize:
            co_uninitialize()


def _open_windows_explorer_fallback(target: Path) -> None:
    if target.is_dir():
        subprocess.Popen(["explorer.exe", str(target)])
        return
    subprocess.Popen(f'explorer.exe /select,"{target}"')
