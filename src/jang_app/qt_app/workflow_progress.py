from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.localization import set_translated_text


@dataclass(frozen=True)
class WorkflowStage:
    key: str
    label: str


class WorkflowProgress(QWidget):
    def __init__(self, stages: Iterable[WorkflowStage]) -> None:
        super().__init__()
        self._stages = tuple(stages)
        if not self._stages:
            raise ValueError("WorkflowProgress requires at least one stage.")
        if len({stage.key for stage in self._stages}) != len(self._stages):
            raise ValueError("WorkflowProgress stage keys must be unique.")

        self.stage_items: dict[str, QFrame] = {}
        self.stage_markers: dict[str, QLabel] = {}
        self.stage_labels: dict[str, QLabel] = {}
        self.connectors: list[QFrame] = []
        self._build_ui()
        self.set_status()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for index, stage in enumerate(self._stages):
            if index:
                connector = QFrame()
                connector.setObjectName("WorkflowConnector")
                connector.setFixedHeight(1)
                layout.addWidget(connector, 1)
                self.connectors.append(connector)

            item = QFrame()
            item.setObjectName("WorkflowStage")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(5)
            item_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            marker = QLabel(str(index + 1))
            marker.setObjectName("WorkflowStageMarker")
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setFixedSize(24, 24)
            label = QLabel()
            label.setObjectName("WorkflowStageLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_translated_text(label, stage.label)

            item_layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignCenter)
            item_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(item, 0)
            self.stage_items[stage.key] = item
            self.stage_markers[stage.key] = marker
            self.stage_labels[stage.key] = label

    def set_status(
        self,
        active_key: str = "",
        *,
        completed_keys: Iterable[str] = (),
        failed: bool = False,
    ) -> None:
        known_keys = {stage.key for stage in self._stages}
        if active_key and active_key not in known_keys:
            raise ValueError(f"Unknown workflow stage: {active_key}")
        completed = set(completed_keys) & known_keys

        for stage in self._stages:
            if stage.key in completed:
                state = "complete"
            elif stage.key == active_key:
                state = "failed" if failed else "active"
            else:
                state = "pending"
            self._set_state(self.stage_items[stage.key], state)
            self._set_state(self.stage_markers[stage.key], state)
            self._set_state(self.stage_labels[stage.key], state)

        for index, connector in enumerate(self.connectors):
            previous_key = self._stages[index].key
            self._set_state(
                connector,
                "complete" if previous_key in completed else "pending",
            )

    def stage_state(self, key: str) -> str:
        item = self.stage_items.get(key)
        if item is None:
            raise ValueError(f"Unknown workflow stage: {key}")
        return str(item.property("stageState") or "")

    @staticmethod
    def _set_state(widget: QWidget, state: str) -> None:
        if widget.property("stageState") == state:
            return
        widget.setProperty("stageState", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
