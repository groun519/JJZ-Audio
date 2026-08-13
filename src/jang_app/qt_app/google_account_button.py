from __future__ import annotations

from pathlib import Path
from time import monotonic

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QProgressBar,
    QVBoxLayout,
    QWidgetAction,
)

from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.google_drive import GoogleDriveQuota
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
        self._quota: GoogleDriveQuota | None = None
        self._account_menu: QMenu | None = None
        self._menu_hidden_at = 0.0
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
        if account is None:
            self._quota = None
        self._unavailable = False
        self._set_connected_property(account is not None)
        self.setEnabled(not self._busy)
        self.apply_language()

    def set_quota(self, quota: GoogleDriveQuota | None) -> None:
        self._quota = quota
        self.apply_language()

    def set_unavailable(self, detail: str) -> None:
        self._account = None
        self._quota = None
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
            if self._quota is not None and self._quota.available_bytes is not None:
                self.setToolTip(
                    tr(
                        "Google Drive  /  {email}  /  {available} left",
                        email=self._account.email,
                        available=_format_quota_bytes(self._quota.available_bytes),
                    )
                )
            else:
                self.setToolTip(f"Google Drive  /  {self._account.email}")
        elif not self._unavailable:
            self.setToolTip(tr("Sign in to Google Drive"))
        self.setAccessibleName(self.toolTip())
        self._rebuild_account_menu()

    def _handle_clicked(self) -> None:
        if self._account is None:
            self.connect_requested.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        menu = self._account_menu
        menu_was_just_hidden = monotonic() - self._menu_hidden_at < 0.2
        if (
            event.button() == Qt.MouseButton.LeftButton
            and menu is not None
            and (menu.isVisible() or menu_was_just_hidden)
        ):
            if menu.isVisible():
                menu.hide()
            self.setDown(False)
            event.accept()
            return
        super().mousePressEvent(event)

    def _rebuild_account_menu(self) -> None:
        previous_menu = self._account_menu
        if self._account is None:
            self._account_menu = None
            self.setMenu(None)
            if previous_menu is not None:
                previous_menu.deleteLater()
            return

        menu = QMenu(self)
        summary_action = QWidgetAction(menu)
        summary_action.setDefaultWidget(
            _GoogleDriveStorageSummary(self._account, self._quota, menu)
        )
        menu.addAction(summary_action)
        menu.addSeparator()
        switch_action = menu.addAction(tr("Switch Google account"))
        disconnect_action = menu.addAction(tr("Disconnect Google Drive"))
        switch_action.triggered.connect(self.switch_requested.emit)
        disconnect_action.triggered.connect(self.disconnect_requested.emit)
        menu.aboutToHide.connect(self._record_menu_hide)
        self._account_menu = menu
        self.setMenu(menu)
        if previous_menu is not None:
            previous_menu.deleteLater()

    def _record_menu_hide(self) -> None:
        self._menu_hidden_at = monotonic()

    def _set_connected_property(self, is_connected: bool) -> None:
        self.setProperty("connected", is_connected)
        self.setIcon(self._color_icon if is_connected else self._inactive_icon)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class _GoogleDriveStorageSummary(QFrame):
    def __init__(
        self,
        account: GoogleAccount,
        quota: GoogleDriveQuota | None,
        parent: QMenu,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("GoogleStorageSummary")
        self.setFixedWidth(250)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(3)

        identity = QLabel(account.display_name)
        identity.setObjectName("GoogleStorageIdentity")
        email = QLabel(account.email)
        email.setObjectName("GoogleStorageEmail")
        layout.addWidget(identity)
        layout.addWidget(email)

        progress = QProgressBar()
        progress.setObjectName("GoogleStorageBar")
        progress.setRange(0, 1000)
        progress.setTextVisible(False)
        progress.setFixedHeight(7)

        used_ratio, storage_state = _quota_visual(quota)
        progress.setProperty("storageState", storage_state)
        progress.setValue(round(used_ratio * progress.maximum()))
        layout.addSpacing(5)
        layout.addWidget(progress)

        detail = QLabel(_quota_detail(quota))
        detail.setObjectName("GoogleStorageDetail")
        detail.setProperty("storageState", storage_state)
        layout.addWidget(detail)


def _quota_visual(quota: GoogleDriveQuota | None) -> tuple[float, str]:
    if quota is None or quota.limit_bytes is None:
        return 0.0, "unknown"
    if quota.limit_bytes <= 0:
        return 1.0, "danger"

    used_ratio = min(1.0, max(0.0, quota.usage_bytes / quota.limit_bytes))
    available_ratio = 1.0 - used_ratio
    if available_ratio <= 0.10:
        return used_ratio, "danger"
    if available_ratio <= 0.20:
        return used_ratio, "warning"
    return used_ratio, "healthy"


def _quota_detail(quota: GoogleDriveQuota | None) -> str:
    if quota is None or quota.available_bytes is None or quota.limit_bytes is None:
        return tr("Storage usage is being checked.")
    return tr(
        "{available} available of {total}",
        available=_format_quota_bytes(quota.available_bytes),
        total=_format_quota_bytes(quota.limit_bytes),
    )


def _monochrome_icon(icon: QIcon, color: QColor) -> QIcon:
    pixmap = icon.pixmap(QSize(32, 32))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return QIcon(pixmap)


def _format_quota_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"
