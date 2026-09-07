from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.startup_timing import StartupTimeline
from jang_app.services.windows_app_mutex import acquire_app_mutex


STARTUP_SMOKE_TEST_ARGUMENT = "--startup-smoke-test"


def main(started_at: float | None = None) -> None:
    smoke_test = STARTUP_SMOKE_TEST_ARGUMENT in sys.argv
    _write_smoke_trace(smoke_test, "entry")
    startup = StartupTimeline(started_at)
    startup.mark("entry_ready")
    mutex = acquire_app_mutex()
    _write_smoke_trace(smoke_test, "mutex_checked")
    if mutex.already_running:
        return
    mutex_handle = mutex.handle

    application_arguments = [
        argument for argument in sys.argv if argument != STARTUP_SMOKE_TEST_ARGUMENT
    ]

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog

    _write_smoke_trace(smoke_test, "qt_imported")
    startup.mark("qt_imported")

    app = QApplication(application_arguments)
    _write_smoke_trace(smoke_test, "application_created")
    startup.mark("application_created")
    from jang_app.qt_app.window_lifecycle import install_window_lifecycle_guard

    install_window_lifecycle_guard(app)
    app._jjzero_mutex_handle = mutex_handle
    app.setApplicationName("JJZero Audio")
    app.setOrganizationName("JJZero")
    package_root = Path(__file__).resolve().parents[1]
    logo_path = package_root / "assets" / "jjzero_logo.svg"
    from jang_app.services.app_paths import discover_app_paths
    from jang_app.services.initial_setup import (
        configure_default_storage,
        is_initial_setup_complete,
    )
    from jang_app.services.rvc_runtime_repair import repair_rvc_runtime_adapter
    from jang_app.services.runtime_installation import recover_runtime_installations

    _write_smoke_trace(smoke_test, "setup_services_imported")
    setup_paths = discover_app_paths(package_root)
    _write_smoke_trace(smoke_test, "paths_discovered")
    startup.mark("paths_discovered")
    from jang_app.services.app_logging import get_logger, install_exception_logging

    logger = get_logger()
    install_exception_logging()
    logger.info("Startup setup phase | state=runtime_recovery_started")
    recover_runtime_installations(setup_paths.runtime_root)
    startup.mark("runtime_recovery_checked")
    # Repair small app-owned runtime overlays before diagnostics inspect the installation.
    repair_rvc_runtime_adapter(setup_paths.runtime_root / "rvc")
    startup.mark("runtime_overlay_repaired")
    logger.info("Startup setup phase | state=runtime_ready")
    setup_complete = is_initial_setup_complete(setup_paths)
    if not setup_complete:
        startup.mark("setup_started")
        logger.info("Startup setup phase | state=initial_setup_started")
        if smoke_test:
            configure_default_storage(setup_paths)
        else:
            from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog

            setup_dialog = InitialSetupDialog(setup_paths, logo_path)
            if setup_dialog.exec() != QDialog.DialogCode.Accepted:
                return
        startup.mark("setup_finished")
        logger.info("Startup setup phase | state=initial_setup_finished")
    elif not smoke_test:
        from jang_app.services.hardware_diagnostics_state import hardware_diagnostics_required

        if hardware_diagnostics_required(setup_paths):
            startup.mark("hardware_diagnostics_started")
            logger.info("Startup setup phase | state=hardware_diagnostics_started")
            from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog

            InitialSetupDialog(
                setup_paths,
                logo_path,
                first_run=False,
                diagnostics_only=True,
            ).exec()
            startup.mark("hardware_diagnostics_finished")
            logger.info("Startup setup phase | state=hardware_diagnostics_finished")

    from jang_app.config import APP_ICON_PATH, APP_NAME

    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    from jang_app.qt_app.startup_coordinator import StartupCoordinator

    coordinator = StartupCoordinator(app, startup, logger)
    if smoke_test:
        from PySide6.QtCore import QTimer

        coordinator.finished.connect(lambda _window: QTimer.singleShot(250, app.quit))
        coordinator.failed.connect(lambda _message: app.exit(1))
    coordinator.start()
    sys.exit(app.exec())


def _write_smoke_trace(enabled: bool, stage: str) -> None:
    if not enabled:
        return
    data_root = os.environ.get("JJZERO_DATA_ROOT", "").strip()
    if not data_root:
        return
    try:
        destination = Path(data_root).expanduser().resolve() / "startup-smoke-trace.log"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(UTC).isoformat()} {stage}\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
