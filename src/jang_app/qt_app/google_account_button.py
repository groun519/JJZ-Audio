from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import QMenu

from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.google_oauth import GoogleAccount
from jang_app.services.i18n import tr


class GoogleAccountButton(FeedbackButton):
    connect_requested = Signal()
    switch_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, icon_path: Path) -> None:
        super().__init__()
        self.setObjectName("GoogleAccountButton")
        self.setFixedSize(30, 26)
        self._color_icon = QIcon(str(icon_path))
        self._inactive_icon = _monochrome_icon(self._color_icon, QColor("#a4a4a4"))
        self.setIconSize(QSize(16, 16))
        self._account: GoogleAccount | None = None
        self._busy = False
        self._unavailable = False
        self.clicked.connect(self._handle_clicked)
        self._set_connected_property(False)
        self.apply_language()

    @property
    def account(self) -> GoogleAccount | None:
        return self._account

    def set_account(self, account: GoogleAccount | None) -> None:
        self._account = account
        self._unavailable = False
        self._set_connected_property(account is not None)
        self.setEnabled(not self._busy)
        self.apply_language()

    def set_unavailable(self, detail: str) -> None:
        self._account = None
        self._unavailable = True
        self._set_connected_property(False)
        self.setEnabled(False)
        self.setToolTip(detail)
        self.setAccessibleName(detail)

    def set_error(self, detail: str) -> None:
        self._unavailable = False
        self.setEnabled(not self._busy)
        self.setToolTip(detail or tr("Sign in to Google Drive"))
        self.setAccessibleName(self.toolTip())

    def set_running(self, is_running: bool) -> None:
        self._busy = is_running
        self.setEnabled(not is_running and not self._unavailable)
        self.apply_language()

    def apply_language(self) -> None:
        if self._busy:
            self.setToolTip(tr("Connecting Google Drive..."))
        elif self._account is not None:
            self.setToolTip(f"Google Drive  /  {self._account.email}")
        elif not self._unavailable:
            self.setToolTip(tr("Sign in to Google Drive"))
        self.setAccessibleName(self.toolTip())

    def _handle_clicked(self) -> None:
        if self._account is None:
            self.connect_requested.emit()
            return
        menu = QMenu(self)
        identity = menu.addAction(self._account.display_name)
        identity.setEnabled(False)
        email = menu.addAction(self._account.email)
        email.setEnabled(False)
        menu.addSeparator()
        switch_action = menu.addAction(tr("Switch Google account"))
        disconnect_action = menu.addAction(tr("Disconnect Google Drive"))
        switch_action.triggered.connect(self.switch_requested.emit)
        disconnect_action.triggered.connect(self.disconnect_requested.emit)
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
        menu.deleteLater()

    def _set_connected_property(self, is_connected: bool) -> None:
        self.setProperty("connected", is_connected)
        self.setIcon(self._color_icon if is_connected else self._inactive_icon)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


def _monochrome_icon(icon: QIcon, color: QColor) -> QIcon:
    pixmap = icon.pixmap(QSize(32, 32))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return QIcon(pixmap)
