from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jang_app.services import file_browser


class FileBrowserTests(unittest.TestCase):
    def test_windows_directory_uses_shell_api_with_exact_resolved_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary, "한글 폴더, 테스트")
            folder.mkdir()
            with (
                patch.object(file_browser.sys, "platform", "win32"),
                patch.object(file_browser, "_open_windows_shell") as shell_open,
                patch.object(file_browser, "_open_windows_explorer_fallback") as fallback,
            ):
                opened = file_browser.open_in_file_browser(folder)

        self.assertEqual(opened, folder.resolve())
        shell_open.assert_called_once_with(folder.resolve())
        fallback.assert_not_called()

    def test_windows_file_uses_shell_api_instead_of_explorer_argument_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary, "보컬 결과, 최종.wav")
            target.write_bytes(b"audio")
            with (
                patch.object(file_browser.sys, "platform", "win32"),
                patch.object(file_browser, "_open_windows_shell") as shell_open,
                patch.object(file_browser, "_open_windows_explorer_fallback") as fallback,
            ):
                opened = file_browser.open_in_file_browser(target)

        self.assertEqual(opened, target.resolve())
        shell_open.assert_called_once_with(target.resolve())
        fallback.assert_not_called()

    def test_windows_shell_failure_uses_quoted_explorer_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary, "result, final.wav")
            target.write_bytes(b"audio")
            with (
                patch.object(file_browser.sys, "platform", "win32"),
                patch.object(file_browser, "_open_windows_shell", side_effect=OSError("shell failed")),
                patch.object(file_browser, "start_detached_command", return_value=True) as start,
            ):
                file_browser.open_in_file_browser(target)

        start.assert_called_once_with(("explorer.exe", f'/select,"{target.resolve()}"'))

    def test_missing_target_is_rejected_before_opening_browser(self) -> None:
        target = Path("missing", "file.wav").resolve()
        with patch.object(file_browser, "_open_windows_shell") as shell_open:
            with self.assertRaises(FileNotFoundError):
                file_browser.open_in_file_browser(target)
        shell_open.assert_not_called()

    def test_windows_shell_selects_file_by_pidl_and_balances_com(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary, "보컬 결과.wav")
            target.write_bytes(b"audio")
            shell32 = SimpleNamespace(
                ILCreateFromPathW=MagicMock(return_value=1234),
                SHOpenFolderAndSelectItems=MagicMock(return_value=0),
                ILFree=MagicMock(),
            )
            ole32 = SimpleNamespace(
                CoInitializeEx=MagicMock(return_value=0),
                CoUninitialize=MagicMock(),
            )
            windll = SimpleNamespace(shell32=shell32, ole32=ole32)
            with patch.object(file_browser.ctypes, "windll", windll, create=True):
                file_browser._open_windows_shell(target.resolve())

        shell32.ILCreateFromPathW.assert_called_once_with(str(target.resolve()))
        shell32.SHOpenFolderAndSelectItems.assert_called_once_with(1234, 0, None, 0)
        shell32.ILFree.assert_called_once_with(1234)
        ole32.CoUninitialize.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
