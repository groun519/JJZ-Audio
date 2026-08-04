from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog
from jang_app.services.app_paths import discover_app_paths
from jang_app.services.initial_setup import is_initial_setup_complete
from jang_app.services.system_diagnostics import (
    DiagnosticCheck,
    DiagnosticStatus,
    SystemDiagnostics,
)


class InitialSetupDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_storage_and_diagnostics_complete_first_run_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            media = root / "chosen-media"
            dialog = InitialSetupDialog(
                paths,
                root / "logo.svg",
                diagnostics_worker_type=_ReadyWorker,
            )
            dialog.media_edit.setText(str(media))

            dialog.primary_button.click()
            self.assertEqual(dialog.stack.currentIndex(), 1)
            self.assertEqual(dialog.diagnostic_rows["cuda"].property("status"), "pass")
            dialog.primary_button.click()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dialog.restart_required)
            self.assertTrue(is_initial_setup_complete(dialog.configured_paths))
            self.assertTrue((media / "workspace").is_dir())
            self.assertTrue((media / "output").is_dir())
            dialog.close()

    def test_existing_setup_without_path_change_closes_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            dialog = InitialSetupDialog(
                paths,
                root / "logo.svg",
                first_run=False,
                diagnostics_worker_type=_ReadyWorker,
            )

            dialog.primary_button.click()
            dialog.primary_button.click()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertFalse(dialog.restart_required)
            dialog.close()


class _ReadyWorker(QObject):
    check_ready = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, _paths) -> None:
        super().__init__()
        self._running = False

    def start(self) -> None:
        self._running = True
        checks = tuple(
            DiagnosticCheck(key, title, DiagnosticStatus.PASS, "Ready")
            for key, title in (
                ("storage", "Storage"),
                ("ffmpeg", "FFmpeg"),
                ("demucs", "Demucs"),
                ("rvc_assets", "RVC Assets"),
                ("ai_runtime", "AI Runtime"),
                ("cuda", "NVIDIA GPU"),
            )
        )
        for check in checks:
            self.check_ready.emit(check)
        self.completed.emit(SystemDiagnostics(checks))
        self._running = False
        self.finished.emit()

    def isRunning(self) -> bool:  # noqa: N802
        return self._running


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "data"), "USERPROFILE": str(root / "user")},
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=root / "source",
    )


if __name__ == "__main__":
    unittest.main()
