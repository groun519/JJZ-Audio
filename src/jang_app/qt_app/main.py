from __future__ import annotations

import sys

from jang_app.services.startup_timing import StartupTimeline


def main(started_at: float | None = None) -> None:
    startup = StartupTimeline(started_at)
    startup.mark("entry_ready")

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    startup.mark("qt_imported")

    from jang_app.config import APP_ICON_PATH, APP_NAME
    from jang_app.services.app_logging import get_logger
    from jang_app.services.settings import load_app_settings

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JJZero")
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    startup.mark("application_created")

    settings = load_app_settings()
    startup.mark("settings_loaded")

    from jang_app.qt_app.main_window import MainWindow

    startup.mark("main_window_imported")
    logger = get_logger()

    window = MainWindow(settings)
    startup.mark("main_window_created")
    window.show()
    startup.mark("window_shown")

    def report_event_loop_ready() -> None:
        startup.mark("event_loop_ready")
        logger.info(startup.summary())

    QTimer.singleShot(0, report_event_loop_ready)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
