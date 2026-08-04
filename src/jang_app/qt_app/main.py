from __future__ import annotations

import sys

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
    from PySide6.QtWidgets import QApplication

    startup.mark("qt_imported")

    from jang_app.config import APP_ICON_PATH, APP_NAME
    from jang_app.services.app_logging import get_logger

    app = QApplication(application_arguments)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JJZero")
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    startup.mark("application_created")

    from jang_app.qt_app.startup_coordinator import StartupCoordinator

    logger = get_logger()
    coordinator = StartupCoordinator(app, startup, logger)
    if smoke_test:
        from PySide6.QtCore import QTimer

        coordinator.finished.connect(lambda _window: QTimer.singleShot(250, app.quit))
        coordinator.failed.connect(lambda _message: app.exit(1))
    coordinator.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
