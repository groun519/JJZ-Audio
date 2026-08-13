from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.share_progress_action import ShareProgressAction
from jang_app.qt_app.widgets import DangerIconButton
from jang_app.services.i18n import tr
from jang_app.services.rvc_model_workspace import RvcModelRecord


class ModelListRow(QWidget):
    activated = Signal(str)
    share_requested = Signal(str)
    delete_share_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        record: RvcModelRecord,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModelListRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_id = record.model_id
        self._sharing_enabled = True

        self.name_label = QLabel()
        self.name_label.setObjectName("ModelRowTitle")

        self.detail_label = QLabel()
        self.detail_label.setObjectName("ModelRowMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.detail_label)

        self.share_action = ShareProgressAction(
            button_size=32,
            reveal_on_hover=True,
            parent=self,
        )
        self.share_action.setObjectName("ModelRowShareAction")
        self.share_action.requested.connect(
            lambda: self.share_requested.emit(self._model_id)
        )
        self.share_action.delete_requested.connect(
            lambda: self.delete_share_requested.emit(self._model_id)
        )
        self.share_button = self.share_action.button

        self.remove_button = DangerIconButton(size=36, paint_inset=2)
        set_translated_tooltip(self.remove_button, "Delete model and work")
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self._model_id)
        )
        self.remove_button.hide()

        self.action_slot = QWidget()
        self.action_slot.setObjectName("ModelRowActionSlot")
        self.action_slot.setFixedSize(163, 42)
        action_layout = QHBoxLayout(self.action_slot)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(7)
        action_layout.addWidget(self.share_action)
        action_layout.addWidget(self.remove_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.action_slot, 0)
        self.update_record(record)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 82)

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.share_action.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)

    def update_record(self, record: RvcModelRecord) -> None:
        self._record = record
        self._model_id = record.model_id
        self.name_label.setText(record.title)
        self.name_label.setToolTip(record.name if record.display_name else "")
        self.detail_label.setText(_record_summary(record))
        self._can_share = record.can_convert
        self.share_action.set_feature_enabled(self._sharing_enabled and self._can_share)

    def apply_language(self) -> None:
        self.update_record(self._record)
        self.share_action.apply_language()
        set_translated_tooltip(self.remove_button, "Delete model and work")

    def set_sharing_enabled(self, is_enabled: bool) -> None:
        self._sharing_enabled = is_enabled
        self.share_action.set_feature_enabled(is_enabled and self._can_share)

    def set_share_started(self) -> None:
        self.share_action.set_running(True)

    def set_share_progress(self, progress: int) -> None:
        self.share_action.set_progress(progress)

    def set_share_completed(self) -> None:
        self.share_action.set_completed()

    def set_share_failed(self) -> None:
        self.share_action.set_failed()

    def set_shared(self, is_shared: bool) -> None:
        self.share_action.set_shared(is_shared)

    def set_share_deleted(self) -> None:
        self.share_action.set_running(False)
        self.share_action.set_deleted()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.share_action.set_idle_visible(True)
        self.share_action.set_actions_expanded(True)
        self.remove_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.share_action.set_idle_visible(False)
        self.share_action.set_actions_expanded(False)
        self.remove_button.hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self._model_id)
        super().mouseReleaseEvent(event)


def _record_summary(record: RvcModelRecord) -> str:
    parts = [
        _format_size(record.total_size_bytes),
        tr(record.status_label),
        tr(record.mode_label),
    ]
    return "  /  ".join(parts)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} GB"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.0f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"
