from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from jang_app.qt_app.widgets import WindowTitleBar
from jang_app.qt_app.window_chrome import apply_window_corner_style


class AppDialog(QDialog):
    def __init__(
        self,
        dialog_title: str,
        logo_path: Path,
        *,
        theme_mode: str,
        parent: QWidget | None = None,
        allow_minimize: bool = False,
        allow_maximize: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(dialog_title)
        self.setWindowIcon(QIcon(str(logo_path)))
        self.setModal(True)

        self.title_bar = WindowTitleBar(
            "JJZero Audio",
            logo_path,
            allow_minimize=allow_minimize,
            allow_maximize=allow_maximize,
        )
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_window_maximized)
        self.title_bar.close_requested.connect(self.reject)
        self.title_bar.set_theme_mode(theme_mode)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("AppDialogContent")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.title_bar)
        root_layout.addWidget(self.content_widget, 1)

    def _toggle_window_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_window_chrome_state()

    def _sync_window_chrome_state(self) -> None:
        self.title_bar.set_maximized(self.isMaximized())
        if self.isVisible():
            apply_window_corner_style(self, rounded=not self.isMaximized())

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_window_chrome_state()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_window_chrome_state()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            apply_window_corner_style(self, rounded=not self.isMaximized())
