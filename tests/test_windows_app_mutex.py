from __future__ import annotations

import ctypes
import os
import unittest
from pathlib import Path

from jang_app.services.windows_app_mutex import APP_MUTEX_NAME, create_app_mutex


class WindowsAppMutexTests(unittest.TestCase):
    def test_installer_uses_application_mutex_name(self) -> None:
        installer_script = (
            Path(__file__).resolve().parents[1] / "packaging" / "JJZeroAudio.iss"
        ).read_text(encoding="utf-8")

        self.assertIn(f"AppMutex={APP_MUTEX_NAME}", installer_script)

    @unittest.skipUnless(os.name == "nt", "Windows mutex is only available on Windows")
    def test_creates_named_windows_mutex(self) -> None:
        handle = create_app_mutex()
        self.assertIsInstance(handle, int)
        self.assertGreater(handle, 0)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        self.assertTrue(kernel32.CloseHandle(handle))
