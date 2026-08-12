from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QSizePolicy

from jang_app.qt_app.navigation_work_song_selector import NavigationWorkSongSelector
from jang_app.qt_app.widgets import FeedbackButton, TransparentContainer, render_app_icon


_PAGE_ICONS = {
    "Library": "database",
    "Models": "model",
    "Vocal": "vocal",
    "Separation": "split",
    "Conversion": "vocal",
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


class NavigationActionButton(FeedbackButton):
    def __init__(self, icon_name: str, accessible_name: str) -> None:
        super().__init__()
        self.setObjectName("NavigationActionButton")
        self.setFixedSize(38, 38)
        self.setAccessibleName(accessible_name)
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
            is_selected=False,
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
            QRectF(rect.center().x() - 9, rect.center().y() - 9, 18, 18),
            self._icon_name,
            palette["foreground"],
        )

        if bool(self.property("keyboardFocus")):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette["focus"], 1))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 9, 9)


class PrimaryNavigationBar(QFrame):
    page_requested = Signal(int)
    settings_requested = Signal()
    work_song_changed = Signal(str)

    def __init__(
        self,
        leading_pages: Iterable[tuple[str, int]],
        workflow_pages: Iterable[tuple[str, int]],
        export_page: tuple[str, int],
    ) -> None:
        super().__init__()
        self.setObjectName("NavigationDock")
        self.setFixedHeight(66)
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
        self.work_song_selector = NavigationWorkSongSelector()
        self.work_song_selector.song_changed.connect(self.work_song_changed.emit)
        self.settings_button = NavigationActionButton("settings", "Settings")
        self.settings_button.clicked.connect(self.settings_requested.emit)

        self.data_divider = _navigation_divider()
        self.export_divider = _navigation_divider()
        self.settings_divider = _navigation_divider()

        self.leading_slot = _NavigationSideSlot()
        leading_layout = QHBoxLayout(self.leading_slot)
        leading_layout.setContentsMargins(0, 0, 0, 0)
        leading_layout.setSpacing(0)
        leading_layout.addWidget(self.work_song_selector, 0, Qt.AlignmentFlag.AlignLeft)

        self.channel_slot = TransparentContainer(object_name="NavigationChannelSlot")
        channel_layout = QHBoxLayout(self.channel_slot)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(4)
        for button in self.leading_buttons:
            channel_layout.addWidget(button)
        channel_layout.addSpacing(12)
        channel_layout.addWidget(self.data_divider)
        channel_layout.addSpacing(12)
        for button in self.workflow_buttons:
            channel_layout.addWidget(button)
        channel_layout.addSpacing(12)
        channel_layout.addWidget(self.export_divider)
        channel_layout.addSpacing(12)
        channel_layout.addWidget(self.export_button)

        self.trailing_slot = _NavigationSideSlot()
        trailing_layout = QHBoxLayout(self.trailing_slot)
        trailing_layout.setContentsMargins(0, 0, 0, 0)
        trailing_layout.setSpacing(12)
        trailing_layout.addStretch(1)
        trailing_layout.addWidget(self.settings_divider)
        trailing_layout.addWidget(self.settings_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)
        layout.addWidget(self.leading_slot, 1)
        layout.addWidget(self.channel_slot, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.trailing_slot, 1)

        self.button_group.idClicked.connect(self.page_requested.emit)
        self.set_current_page(leading_items[0][1])

    def set_current_page(self, page_id: int) -> None:
        button = self.button_group.button(page_id)
        if button is not None:
            button.setChecked(True)

    def set_page_enabled(
        self,
        page_id: int,
        enabled: bool,
        *,
        disabled_tooltip: str = "",
    ) -> None:
        button = self.button_group.button(page_id)
        if button is None:
            return
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else disabled_tooltip)

    def set_work_songs(
        self,
        songs: Iterable[tuple[str, str]],
        selected_id: str = "",
    ) -> None:
        self.work_song_selector.set_songs(songs, selected_id)

    def select_work_song(self, song_id: str) -> None:
        self.work_song_selector.select_song(song_id)

    def apply_language(self) -> None:
        self.work_song_selector.apply_language()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.work_song_selector.set_theme_mode(theme_mode)
        for button in self.buttons:
            button.set_theme_mode(theme_mode)
        self.settings_button.set_theme_mode(theme_mode)

    def _add_button(self, label: str, page_id: int) -> NavigationItemButton:
        button = NavigationItemButton(label, _PAGE_ICONS.get(label, "missing"))
        self.button_group.addButton(button, page_id)
        return button


def _navigation_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("NavigationGroupDivider")
    divider.setFixedSize(1, 20)
    return divider


class _NavigationSideSlot(TransparentContainer):
    def __init__(self) -> None:
        super().__init__(object_name="NavigationSideSlot")
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(344, 50)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, 50)


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
