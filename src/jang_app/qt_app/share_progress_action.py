from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from jang_app.qt_app.localization import set_translated_text, set_translated_tooltip
from jang_app.qt_app.widgets import DangerIconButton, FeedbackButton, SvgIconButton


class ShareProgressAction(QWidget):
    """Compact row action that swaps a share icon for inline upload progress."""

    requested = Signal()
    delete_requested = Signal()

    def __init__(
        self,
        *,
        button_size: int = 30,
        reveal_on_hover: bool = False,
        share_tooltip: str = "Share with Google Drive",
        copy_tooltip: str = "Copy Google Drive link",
        delete_tooltip: str = "Delete from Google Drive",
        copied_text: str = "Copied",
        button_text: str = "",
        shared_button_text: str = "",
        button_width: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ShareProgressAction")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        button_extent = button_size + 4
        action_width = max(88, int(button_width)) if button_text else 0
        widget_width = 120 if not button_text else action_width + button_extent + 9
        self.setFixedSize(widget_width, max(38, button_extent + 4))
        self._feature_enabled = True
        self._idle_visible = not reveal_on_hover
        self._reserve_idle_space = reveal_on_hover
        self._running = False
        self._shared = False
        self._actions_expanded = False
        self._copied_visible = False
        self._share_tooltip = share_tooltip
        self._copy_tooltip = copy_tooltip
        self._delete_tooltip = delete_tooltip
        self._copied_text = copied_text
        self._button_text = button_text
        self._shared_button_text = shared_button_text

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
        set_translated_text(self.copied_label, self._copied_text)

        if self._button_text:
            self.button = FeedbackButton()
            self.button.setFixedSize(action_width, button_extent)
            self.button.setObjectName("WorkShareButton")
            set_translated_text(self.button, self._button_text)
        else:
            self.button = SvgIconButton("link", size=button_extent, paint_inset=2)
            self.button.setObjectName("RowShareButton")
        self._sync_share_tooltip()
        self.button.clicked.connect(self.requested.emit)

        self.delete_button = DangerIconButton(size=button_extent, paint_inset=2)
        set_translated_tooltip(self.delete_button, self._delete_tooltip)
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
        if isinstance(self.button, SvgIconButton):
            self.button.set_theme_mode(theme_mode)
        self.delete_button.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        set_translated_text(self.copied_label, self._copied_text)
        self._sync_button_text()
        self._sync_share_tooltip()
        set_translated_tooltip(self.delete_button, self._delete_tooltip)

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
        if isinstance(self.button, SvgIconButton):
            self.button.setObjectName("RowSharedButton" if is_shared else "RowShareButton")
            self.button.set_icon_name("cloud_check" if is_shared else "link")
        else:
            self.button.setObjectName(
                "WorkSharedButton" if is_shared else "WorkShareButton"
            )
            self._sync_button_text()
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
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
            self._copy_tooltip if self._shared else self._share_tooltip,
        )

    def _sync_button_text(self) -> None:
        if not self._button_text:
            return
        source = (
            self._shared_button_text
            if self._shared and self._shared_button_text
            else self._button_text
        )
        set_translated_text(self.button, source)
