from __future__ import annotations

import os
import unittest
from pathlib import Path

from jang_app.services.windows_app_mutex import APP_MUTEX_NAME, close_app_mutex, create_app_mutex


class WindowsAppMutexTests(unittest.TestCase):
    def test_installer_allows_only_internal_updates_while_app_is_running(self) -> None:
        installer_script = (
            Path(__file__).resolve().parents[1] / "packaging" / "JJZeroAudio.iss"
        ).read_text(encoding="utf-8")

        self.assertIn(f'#define AppMutexName "{APP_MUTEX_NAME}"', installer_script)
        self.assertNotIn("AppMutex={#AppMutexName}", installer_script)
        self.assertIn("CheckForMutexes('{#AppMutexName}')", installer_script)
        self.assertIn("HasCommandLineSwitch('/RUN')", installer_script)
        self.assertIn("function InitializeUninstall: Boolean;", installer_script)

    @unittest.skipUnless(os.name == "nt", "Windows mutex is only available on Windows")
    def test_creates_named_windows_mutex(self) -> None:
        handle = create_app_mutex()
        self.assertIsInstance(handle, int)
        self.assertGreater(handle, 0)

        self.assertTrue(close_app_mutex(handle))
