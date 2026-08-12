from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import DangerIconButton, SvgIconButton


class ShareProgressAction(QWidget):
    """Compact row action that swaps a share icon for inline upload progress."""

    requested = Signal()
    delete_requested = Signal()

    def __init__(
        self,
        *,
        button_size: int = 30,
        reveal_on_hover: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ShareProgressAction")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        button_extent = button_size + 4
        self.setFixedSize(120, max(38, button_extent + 4))
        self._feature_enabled = True
        self._idle_visible = not reveal_on_hover
        self._reserve_idle_space = reveal_on_hover
        self._running = False
        self._shared = False
        self._actions_expanded = False
        self._copied_visible = False

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("RowShareProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedSize(52, 4)

        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("RowShareProgressLabel")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_label.setFixedWidth(34)

        self.copied_label = QLabel()
        self.copied_label.setObjectName("ShareCopiedLabel")
        self.copied_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copied_label.setFixedSize(66, 28)
        set_translated_text(self.copied_label, "Copied")

        self.button = SvgIconButton("link", size=button_extent, paint_inset=2)
        self.button.setObjectName("RowShareButton")
        set_translated_tooltip(self.button, "Share with Google Drive")
        self.button.clicked.connect(self.requested.emit)

        self.delete_button = DangerIconButton(size=button_extent, paint_inset=2)
        set_translated_tooltip(self.delete_button, "Delete from Google Drive")
        self.delete_button.clicked.connect(self.delete_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addStretch(1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.copied_label)
        layout.addWidget(self.button)
        layout.addWidget(self.delete_button)

        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(1800)
        self._completion_timer.timeout.connect(self._finish)
        self.progress_bar.hide()
        self.progress_label.hide()
        self.copied_label.hide()
        self.delete_button.hide()
        self._sync_visibility()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.button.set_theme_mode(theme_mode)
        self.delete_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_text(self.copied_label, "Copied")
        self._sync_share_tooltip()
        set_translated_tooltip(self.delete_button, "Delete from Google Drive")

    def set_feature_enabled(self, is_enabled: bool) -> None:
        self._feature_enabled = is_enabled
        self.button.setEnabled(is_enabled and not self._running)
        self.delete_button.setEnabled(is_enabled and not self._running)
        self._sync_visibility()

    def set_idle_visible(self, is_visible: bool) -> None:
        self._idle_visible = is_visible
        self._sync_visibility()

    def set_actions_expanded(self, is_expanded: bool) -> None:
        self._actions_expanded = is_expanded
        self._sync_visibility()

    def set_shared(self, is_shared: bool) -> None:
        self._shared = is_shared
        self.button.setObjectName("RowSharedButton" if is_shared else "RowShareButton")
        self.button.set_icon_name("cloud_check" if is_shared else "link")
        self._sync_share_tooltip()
        self._sync_visibility()

    def set_running(self, is_running: bool) -> None:
        self._completion_timer.stop()
        self._running = is_running
        self._copied_visible = False
        self.button.setEnabled(self._feature_enabled and not is_running)
        if is_running:
            self.set_progress(0)
        self._sync_visibility()

    def set_progress(self, progress: int) -> None:
        value = max(0, min(100, int(progress)))
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"{value}%")

    def set_completed(self) -> None:
        self._completion_timer.stop()
        self.set_shared(True)
        self._running = False
        self._copied_visible = True
        self._sync_visibility()
        self._completion_timer.start()

    def set_failed(self) -> None:
        self._completion_timer.stop()
        self._finish()

    def set_deleted(self) -> None:
        self.set_shared(False)

    def _finish(self) -> None:
        self._running = False
        self._copied_visible = False
        self.button.setEnabled(self._feature_enabled)
        self.delete_button.setEnabled(self._feature_enabled)
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        is_visible = self._running or self._copied_visible or (
            self._feature_enabled and (self._idle_visible or self._shared)
        )
        self.setVisible(is_visible or self._reserve_idle_space)
        self.progress_bar.setVisible(self._running)
        self.progress_label.setVisible(self._running)
        self.copied_label.setVisible(self._copied_visible)
        show_buttons = is_visible and not self._running and not self._copied_visible
        self.button.setVisible(show_buttons)
        self.delete_button.setVisible(
            show_buttons and self._shared and self._actions_expanded
        )

    def _sync_share_tooltip(self) -> None:
        set_translated_tooltip(
            self.button,
            "Copy Google Drive link" if self._shared else "Share with Google Drive",
        )
