from __future__ import annotations

import sys
from pathlib import Path

from jang_app.services.startup_timing import StartupTimeline


STARTUP_SMOKE_TEST_ARGUMENT = "--startup-smoke-test"


def main(started_at: float | None = None) -> None:
    startup = StartupTimeline(started_at)
    startup.mark("entry_ready")

    smoke_test = STARTUP_SMOKE_TEST_ARGUMENT in sys.argv
    application_arguments = [
        argument for argument in sys.argv if argument != STARTUP_SMOKE_TEST_ARGUMENT
    ]

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog

    startup.mark("qt_imported")

    app = QApplication(application_arguments)
    app.setApplicationName("JJZero Audio")
    app.setOrganizationName("JJZero")
    package_root = Path(__file__).resolve().parents[1]
    logo_path = package_root / "assets" / "jjzero_logo.svg"
    from jang_app.services.app_paths import discover_app_paths
    from jang_app.services.initial_setup import (
        configure_default_storage,
        is_initial_setup_complete,
    )

    setup_paths = discover_app_paths(package_root)
    if not is_initial_setup_complete(setup_paths):
        if smoke_test:
            configure_default_storage(setup_paths)
        else:
            from jang_app.qt_app.initial_setup_dialog import InitialSetupDialog

            setup_dialog = InitialSetupDialog(setup_paths, logo_path)
            if setup_dialog.exec() != QDialog.DialogCode.Accepted:
                return

    from jang_app.config import APP_ICON_PATH, APP_NAME
    from jang_app.services.app_logging import get_logger, install_exception_logging

    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    startup.mark("application_created")

    from jang_app.qt_app.startup_coordinator import StartupCoordinator

    logger = get_logger()
    install_exception_logging()
    coordinator = StartupCoordinator(app, startup, logger)
    if smoke_test:
        from PySide6.QtCore import QTimer

        coordinator.finished.connect(lambda _window: QTimer.singleShot(250, app.quit))
        coordinator.failed.connect(lambda _message: app.exit(1))
    coordinator.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
