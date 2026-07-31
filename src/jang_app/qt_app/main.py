from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from jang_app.config import APP_ICON_PATH, APP_NAME
from jang_app.qt_app.main_window import MainWindow
from jang_app.services.settings import load_app_settings


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JJZero")
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    window = MainWindow(load_app_settings())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
