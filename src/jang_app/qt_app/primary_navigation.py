from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout

from jang_app.qt_app.widgets import FeedbackButton


class PrimaryNavigationBar(QFrame):
    page_requested = Signal(int)

    def __init__(
        self,
        leading_pages: Iterable[tuple[str, int]],
        workflow_pages: Iterable[tuple[str, int]],
        export_page: tuple[str, int],
    ) -> None:
        super().__init__()
        self.setObjectName("NavigationBar")
        leading_items = tuple(leading_pages)
        workflow_items = tuple(workflow_pages)
        if not leading_items or not workflow_items:
            raise ValueError("PrimaryNavigationBar requires leading and workflow pages")

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.leading_buttons: list[FeedbackButton] = []
        for label, page_id in leading_items:
            button = _navigation_button(label, "StandaloneNavButton")
            self.button_group.addButton(button, page_id)
            self.leading_buttons.append(button)

        workflow_rail = QFrame()
        workflow_rail.setObjectName("WorkflowNavigationRail")
        workflow_layout = QHBoxLayout(workflow_rail)
        workflow_layout.setContentsMargins(3, 3, 3, 3)
        workflow_layout.setSpacing(2)
        self.workflow_buttons: list[FeedbackButton] = []
        for label, page_id in workflow_items:
            button = _navigation_button(label, "WorkflowNavButton")
            self.button_group.addButton(button, page_id)
            self.workflow_buttons.append(button)
            workflow_layout.addWidget(button, 0)

        export_label, export_id = export_page
        self.export_button = _navigation_button(export_label, "ExportNavButton")
        self.button_group.addButton(self.export_button, export_id)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(14)
        layout.addStretch(1)
        for button in self.leading_buttons:
            layout.addWidget(button, 0)
        layout.addWidget(workflow_rail, 0)
        layout.addWidget(self.export_button, 0)
        layout.addStretch(1)

        self.button_group.idClicked.connect(self.page_requested.emit)
        self.set_current_page(leading_items[0][1])

    def set_current_page(self, page_id: int) -> None:
        button = self.button_group.button(page_id)
        if button is not None:
            button.setChecked(True)


def _navigation_button(label: str, object_name: str) -> FeedbackButton:
    button = FeedbackButton(label)
    button.setObjectName(object_name)
    button.setCheckable(True)
    return button
