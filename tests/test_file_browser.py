from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services import file_browser


class FileBrowserTests(unittest.TestCase):
    def test_windows_directory_opens_instead_of_selecting_its_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            with (
                patch.object(file_browser.sys, "platform", "win32"),
                patch.object(file_browser.subprocess, "Popen") as popen,
            ):
                opened = file_browser.open_in_file_browser(folder)

        self.assertEqual(opened, folder)
        popen.assert_called_once_with(["explorer.exe", str(folder)])


if __name__ == "__main__":
    unittest.main()
