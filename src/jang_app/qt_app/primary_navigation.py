from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout

from jang_app.qt_app.widgets import FeedbackButton, render_app_icon


_PAGE_ICONS = {
    "Library": "database",
    "Models": "model",
    "Vocal": "vocal",
    "Studio": "studio",
    "Export": "download",
}


class NavigationItemButton(FeedbackButton):
    def __init__(self, label: str, icon_name: str) -> None:
        super().__init__(label)
        self.setObjectName("NavigationItemButton")
        self.setCheckable(True)
        self.setFixedSize(112, 38)
        self.setAccessibleName(label)
        self._icon_name = icon_name
        self._theme_mode = "white"

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = _navigation_palette(
            self._theme_mode,
            is_selected=self.isChecked(),
            is_hovered=self._is_pointer_hovered(),
            is_pressed=self._is_pointer_pressed() or self.isDown(),
            is_enabled=self.isEnabled(),
        )

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        border = palette["border"]
        painter.setPen(QPen(border, 1) if border.alpha() else Qt.PenStyle.NoPen)
        painter.setBrush(palette["background"])
        painter.drawRoundedRect(rect, 12, 12)
        render_app_icon(
            painter,
            QRectF(15, (rect.height() - 16) / 2, 16, 16),
            self._icon_name,
            palette["foreground"],
        )

        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Bold if self.isChecked() else QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(palette["foreground"])
        painter.drawText(
            QRectF(40, 0, rect.width() - 48, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )

        if bool(self.property("keyboardFocus")):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette["focus"], 1))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 9, 9)


class PrimaryNavigationBar(QFrame):
    page_requested = Signal(int)

    def __init__(
        self,
        leading_pages: Iterable[tuple[str, int]],
        workflow_pages: Iterable[tuple[str, int]],
        export_page: tuple[str, int],
    ) -> None:
        super().__init__()
        self.setObjectName("NavigationDock")
        self.setFixedHeight(54)
        leading_items = tuple(leading_pages)
        workflow_items = tuple(workflow_pages)
        if not leading_items or not workflow_items:
            raise ValueError("PrimaryNavigationBar requires leading and workflow pages")

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.leading_buttons = [self._add_button(label, page_id) for label, page_id in leading_items]
        self.workflow_buttons = [self._add_button(label, page_id) for label, page_id in workflow_items]
        export_label, export_id = export_page
        self.export_button = self._add_button(export_label, export_id)
        self.buttons = (*self.leading_buttons, *self.workflow_buttons, self.export_button)

        self.data_divider = _navigation_divider()
        self.export_divider = _navigation_divider()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(4)
        layout.addStretch(1)
        for button in self.leading_buttons:
            layout.addWidget(button)
        layout.addSpacing(12)
        layout.addWidget(self.data_divider)
        layout.addSpacing(12)
        for button in self.workflow_buttons:
            layout.addWidget(button)
        layout.addSpacing(12)
        layout.addWidget(self.export_divider)
        layout.addSpacing(12)
        layout.addWidget(self.export_button)
        layout.addStretch(1)

        self.button_group.idClicked.connect(self.page_requested.emit)
        self.set_current_page(leading_items[0][1])

    def set_current_page(self, page_id: int) -> None:
        button = self.button_group.button(page_id)
        if button is not None:
            button.setChecked(True)

    def set_theme_mode(self, theme_mode: str) -> None:
        for button in self.buttons:
            button.set_theme_mode(theme_mode)

    def _add_button(self, label: str, page_id: int) -> NavigationItemButton:
        button = NavigationItemButton(label, _PAGE_ICONS.get(label, "missing"))
        self.button_group.addButton(button, page_id)
        return button


def _navigation_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("NavigationGroupDivider")
    divider.setFixedSize(1, 20)
    return divider


def _navigation_palette(
    theme_mode: str,
    *,
    is_selected: bool,
    is_hovered: bool,
    is_pressed: bool,
    is_enabled: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        colors = {
            "idle_text": "#8f8d87",
            "hover_text": "#d6d4ce",
            "selected_text": "#ecebe7",
            "hover_surface": "#20201f",
            "pressed_surface": "#353532",
            "selected_surface": "#2b2b29",
            "selected_border": "#484843",
        }
        focus = QColor("#898780")
    else:
        colors = {
            "idle_text": "#777168",
            "hover_text": "#292824",
            "selected_text": "#10100e",
            "hover_surface": "#eee9df",
            "pressed_surface": "#d9d2c5",
            "selected_surface": "#e7e1d5",
            "selected_border": "#c8c0b2",
        }
        focus = QColor("#6e6a61")
    background = QColor(0, 0, 0, 0)
    foreground = QColor(colors["idle_text"])
    border = QColor(0, 0, 0, 0)
    if is_selected:
        background = QColor(colors["selected_surface"])
        foreground = QColor(colors["selected_text"])
        border = QColor(colors["selected_border"])
    elif is_pressed:
        background = QColor(colors["pressed_surface"])
        foreground = QColor(colors["hover_text"])
    elif is_hovered:
        background = QColor(colors["hover_surface"])
        foreground = QColor(colors["hover_text"])
    if not is_enabled:
        foreground.setAlpha(90)
        border.setAlpha(90)
    return {
        "background": background,
        "foreground": foreground,
        "border": border,
        "focus": focus,
    }
