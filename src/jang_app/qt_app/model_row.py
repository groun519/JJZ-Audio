from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.model_badge import set_model_badge
from jang_app.services.i18n import tr
from jang_app.services.rvc_model_workspace import RvcModelRecord


class ModelListRow(QWidget):
    activated = Signal(str)

    def __init__(self, record: RvcModelRecord) -> None:
        super().__init__()
        self.setObjectName("ModelListRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_id = record.model_id

        self.name_label = QLabel()
        self.name_label.setObjectName("ModelRowTitle")

        self.detail_label = QLabel()
        self.detail_label.setObjectName("ModelRowMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.detail_label)

        self.mode_badge = QLabel()
        self.mode_badge.setObjectName("ModelModeBadge")
        self.mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_badge.setMinimumWidth(68)

        self.status_badge = QLabel()
        self.status_badge.setObjectName("ModelStatusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setMinimumWidth(102)

        badges = QVBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(6)
        badges.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignRight)
        badges.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignRight)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.addLayout(text_layout, 1)
        layout.addLayout(badges, 0)
        self.update_record(record)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 82)

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_record(self, record: RvcModelRecord) -> None:
        self._record = record
        self._model_id = record.model_id
        self.name_label.setText(record.title)
        self.name_label.setToolTip(record.name if record.display_name else "")
        self.detail_label.setText(_record_summary(record))
        set_model_badge(self.status_badge, record.status_label, "status", record.status_key)
        set_model_badge(self.mode_badge, record.mode_label, "managed", record.is_managed)

    def apply_language(self) -> None:
        self.update_record(self._record)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self._model_id)
        super().mouseReleaseEvent(event)


def _record_summary(record: RvcModelRecord) -> str:
    parts = [_format_size(record.total_size_bytes)]
    if record.has_index:
        parts.append(tr("Index"))
    if record.can_resume:
        parts.append(tr("G/D checkpoint"))
    return "  /  ".join(parts)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} GB"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.0f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"
