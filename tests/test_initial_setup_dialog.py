from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog

from jang_app.qt_app.initial_setup_dialog import DiagnosticRow, InitialSetupDialog
from jang_app.services.app_paths import discover_app_paths
from jang_app.services.initial_setup import is_initial_setup_complete
from jang_app.services.storage_migration import migrate_storage, plan_storage_migration
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
                storage_worker_type=_ReadyStorageWorker,
            )
            self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertEqual(dialog.title_bar.objectName(), "WindowTitleBar")
            dialog.media_edit.setText(str(media))

            dialog.primary_button.click()
            self.assertEqual(dialog.stack.currentIndex(), 1)
            self.assertEqual(dialog.diagnostic_rows["cuda"].property("status"), "pass")
            dialog.primary_button.click()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dialog.restart_required)
            self.assertTrue(is_initial_setup_complete(dialog.configured_paths))
            self.assertTrue((media / "Data").is_dir())
            self.assertTrue((media / "Output").is_dir())
            self.assertTrue((media / "Runtime").is_dir())
            dialog.close()

    def test_existing_v1_setup_upgrades_layout_and_requests_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            dialog = InitialSetupDialog(
                paths,
                root / "logo.svg",
                first_run=False,
                diagnostics_worker_type=_ReadyWorker,
                storage_worker_type=_ReadyStorageWorker,
            )

            dialog.primary_button.click()
            dialog.primary_button.click()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dialog.restart_required)
            self.assertEqual(dialog.configured_paths.storage_version, 2)
            dialog.close()

    def test_diagnostic_row_keeps_wrapped_detail_visible(self) -> None:
        row = DiagnosticRow("RVC Assets")
        row.set_pending(
            "Runtime package and model verification has not been run yet."
        )
        row.resize(520, 30)
        row.show()
        self.app.processEvents()

        self.assertTrue(row.detail_label.wordWrap())
        self.assertGreaterEqual(row.height(), row.minimumHeight())
        self.assertGreaterEqual(
            row.detail_label.height(),
            row.detail_label.minimumHeight(),
        )
        self.assertLessEqual(
            row.detail_label.geometry().bottom(),
            row.contentsRect().bottom(),
        )
        row.close()


class _ReadyWorker(QObject):
    check_ready = Signal(object)
    stage_started = Signal(str, int, int)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        _paths,
        *,
        refresh_runtime: bool = False,
        refresh_hardware: bool = False,
    ) -> None:
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
        for position, check in enumerate(checks, start=1):
            self.stage_started.emit(check.key, position, len(checks))
            self.check_ready.emit(check)
        self.completed.emit(SystemDiagnostics(checks))
        self._running = False
        self.finished.emit()

    def isRunning(self) -> bool:  # noqa: N802
        return self._running


class _ReadyStorageWorker(QObject):
    plan_ready = Signal(object)
    progress_changed = Signal(str, int)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, paths, storage_root: Path) -> None:
        super().__init__()
        self._paths = paths
        self._storage_root = storage_root
        self._running = False

    def start(self) -> None:
        self._running = True
        try:
            plan = plan_storage_migration(self._paths, self._storage_root)
            self.plan_ready.emit(plan)
            configured = migrate_storage(
                plan,
                lambda stage, value: self.progress_changed.emit(stage, value),
            )
            self.completed.emit(configured)
        except Exception as exc:
            self.failed.emit(str(exc))
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
