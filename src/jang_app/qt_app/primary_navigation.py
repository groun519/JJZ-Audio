from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
)

from jang_app.qt_app.navigation_work_song_selector import NavigationWorkSongSelector
from jang_app.qt_app.widgets import FeedbackButton, TransparentContainer, render_app_icon
from jang_app.qt_app.window_lifecycle import allow_top_level_window
from jang_app.services.i18n import tr


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
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, label: str, icon_name: str) -> None:
        super().__init__(label)
        self.setObjectName("NavigationItemButton")
        self.setCheckable(True)
        self.setFixedSize(112, 38)
        self.setAccessibleName(label)
        self._icon_name = icon_name
        self._theme_mode = "white"
        self._has_submenu = False

    def set_has_submenu(self, has_submenu: bool) -> None:
        self._has_submenu = bool(has_submenu)
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.hover_entered.emit()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.hover_left.emit()

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

        if self._has_submenu:
            chevron = QPen(palette["foreground"], 1.4)
            chevron.setCapStyle(Qt.PenCapStyle.RoundCap)
            chevron.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(chevron)
            center_x = rect.right() - 8
            center_y = rect.center().y()
            painter.drawLine(
                QPoint(int(center_x - 3), int(center_y - 1)),
                QPoint(int(center_x), int(center_y + 2)),
            )
            painter.drawLine(
                QPoint(int(center_x), int(center_y + 2)),
                QPoint(int(center_x + 3), int(center_y - 1)),
            )

        if bool(self.property("keyboardFocus")):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette["focus"], 1))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 9, 9)


class _NavigationSubmenuOption(FeedbackButton):
    def __init__(self, option: str, label: str) -> None:
        super().__init__(label)
        self.option = option
        self._theme_mode = "white"
        self.setCheckable(True)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)

    def set_label(self, label: str) -> None:
        self.setText(label)
        self.setAccessibleName(label)
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dark = self._theme_mode == "dark"
        enabled = self.isEnabled()
        selected = self.isChecked() and enabled
        hovered = self._is_pointer_hovered() and enabled
        pressed = (self._is_pointer_pressed() or self.isDown()) and enabled
        background = QColor(0, 0, 0, 0)
        if pressed:
            background = QColor("#353532" if dark else "#ddd6ca")
        elif hovered or selected:
            background = QColor("#292927" if dark else "#ede7dc")
        foreground = QColor("#777570" if dark else "#a29c91")
        if enabled:
            foreground = QColor("#ecebe7" if dark else "#24231f")
        if enabled and not hovered and not selected:
            foreground = QColor("#aaa8a2" if dark else "#6f6b63")

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 8, 8)
        if selected:
            painter.setBrush(QColor("#d6a13a" if dark else "#a56c16"))
            painter.drawEllipse(QRectF(11, rect.center().y() - 3, 6, 6))

        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(foreground)
        painter.drawText(
            QRectF(26, 0, rect.width() - 34, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )


class _NavigationSubmenu(QFrame):
    option_selected = Signal(str)

    def __init__(
        self,
        options: Iterable[tuple[str, str]],
        parent: QFrame,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("NavigationSubmenu")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        allow_top_level_window(self)
        self._theme_mode = "white"
        self.buttons: dict[str, _NavigationSubmenuOption] = {}
        self.label_keys: dict[str, str] = {}
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        for option, label_key in options:
            button = _NavigationSubmenuOption(option, tr(label_key))
            button.clicked.connect(
                lambda _checked=False, value=option: self.option_selected.emit(value)
            )
            self.button_group.addButton(button)
            layout.addWidget(button)
            self.buttons[option] = button
            self.label_keys[option] = label_key
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        label_font.setWeight(QFont.Weight.DemiBold)
        label_metrics = QFontMetrics(label_font)
        self._minimum_width = max(
            156,
            max(
                (
                    label_metrics.horizontalAdvance(button.text())
                    for button in self.buttons.values()
                ),
                default=0,
            )
            + 48,
        )
        self.setFixedWidth(self._minimum_width)
        self.setFixedHeight(12 + len(self.buttons) * 34 + max(0, len(self.buttons) - 1) * 2)

    def set_selected(self, option: str) -> None:
        button = self.buttons.get(option)
        if button is not None:
            button.setChecked(True)

    def apply_language(self) -> None:
        for option, label_key in self.label_keys.items():
            self.buttons[option].set_label(tr(label_key))

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for button in self.buttons.values():
            button.set_theme_mode(theme_mode)
        self.update()

    def show_for(self, anchor: NavigationItemButton) -> None:
        self.setFixedWidth(max(self._minimum_width, anchor.width()))
        target = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = QApplication.screenAt(target) or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target.setX(
                min(
                    max(target.x(), available.left() + 8),
                    available.right() - self.width() - 8,
                )
            )
        self.move(target)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dark = self._theme_mode == "dark"
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setBrush(QColor("#1b1b19" if dark else "#f7f3eb"))
        painter.setPen(QPen(QColor("#3d3d39" if dark else "#d3ccbf"), 1.25))
        painter.drawRoundedRect(rect, 10, 10)


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
    page_option_requested = Signal(int, str)
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
        self._theme_mode = "white"
        self._page_menus: dict[int, _NavigationSubmenu] = {}
        self._page_menu_actions: dict[int, dict[str, _NavigationSubmenuOption]] = {}
        self._page_menu_labels: dict[int, dict[str, str]] = {}
        self._submenu_close_timers: dict[int, QTimer] = {}

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

        self.button_group.idClicked.connect(self._on_page_clicked)
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

    def set_page_options(
        self,
        page_id: int,
        options: Iterable[tuple[str, str]],
        *,
        selected_option: str,
    ) -> None:
        button = self.button_group.button(page_id)
        if not isinstance(button, NavigationItemButton):
            return
        previous_menu = self._page_menus.pop(page_id, None)
        if previous_menu is not None:
            previous_menu.hide()
            previous_menu.deleteLater()

        menu = _NavigationSubmenu(options, self)
        menu.set_theme_mode(self._theme_mode)
        menu.option_selected.connect(
            lambda value, requested_page=page_id: self._request_page_option(
                requested_page,
                value,
            )
        )
        self._page_menus[page_id] = menu
        self._page_menu_actions[page_id] = menu.buttons
        self._page_menu_labels[page_id] = menu.label_keys
        if page_id not in self._submenu_close_timers:
            close_timer = QTimer(self)
            close_timer.setSingleShot(True)
            close_timer.setInterval(140)
            close_timer.timeout.connect(
                lambda value=page_id: self._close_page_menu_if_unhovered(value)
            )
            self._submenu_close_timers[page_id] = close_timer
            button.hover_entered.connect(
                lambda value=page_id: self._on_submenu_hover_entered(value)
            )
            button.hover_left.connect(
                lambda value=page_id: self._on_submenu_button_left(value)
            )
        button.set_has_submenu(bool(menu.buttons))
        self.set_page_option(page_id, selected_option)

    def set_page_option(self, page_id: int, option: str) -> None:
        menu = self._page_menus.get(page_id)
        if menu is not None:
            menu.set_selected(option)

    def set_page_option_enabled(
        self,
        page_id: int,
        option: str,
        enabled: bool,
        *,
        disabled_tooltip: str = "",
    ) -> None:
        button = self._page_menu_actions.get(page_id, {}).get(option)
        if button is None:
            return
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else disabled_tooltip)
        if not enabled and button.isChecked():
            button.setChecked(False)
        button.update()

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
        for menu in self._page_menus.values():
            menu.apply_language()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.work_song_selector.set_theme_mode(theme_mode)
        for button in self.buttons:
            button.set_theme_mode(theme_mode)
        for menu in self._page_menus.values():
            menu.set_theme_mode(theme_mode)
        self.settings_button.set_theme_mode(theme_mode)

    def _add_button(self, label: str, page_id: int) -> NavigationItemButton:
        button = NavigationItemButton(label, _PAGE_ICONS.get(label, "missing"))
        self.button_group.addButton(button, page_id)
        return button

    def _on_page_clicked(self, page_id: int) -> None:
        self._cancel_page_menu_close(page_id)
        menu = self._page_menus.get(page_id)
        if menu is not None:
            menu.hide()
        self.page_requested.emit(page_id)

    def _on_submenu_hover_entered(self, page_id: int) -> None:
        self._cancel_page_menu_close(page_id)
        self._show_page_menu(page_id)

    def _on_submenu_button_left(self, page_id: int) -> None:
        self._schedule_page_menu_close(page_id)

    def _cancel_page_menu_close(self, page_id: int) -> None:
        timer = self._submenu_close_timers.get(page_id)
        if timer is not None:
            timer.stop()

    def _schedule_page_menu_close(self, page_id: int) -> None:
        timer = self._submenu_close_timers.get(page_id)
        if timer is not None:
            timer.start()

    def _close_page_menu_if_unhovered(self, page_id: int) -> None:
        menu = self._page_menus.get(page_id)
        button = self.button_group.button(page_id)
        if menu is None or button is None:
            return
        button_rect = QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
        menu_rect = QRect(menu.pos(), menu.size())
        if button_rect.united(menu_rect).contains(QCursor.pos()):
            self._schedule_page_menu_close(page_id)
            return
        menu.hide()

    def _show_page_menu(self, page_id: int) -> None:
        menu = self._page_menus.get(page_id)
        button = self.button_group.button(page_id)
        if (
            menu is None
            or button is None
            or not button.isVisible()
            or not button.isEnabled()
            or menu.isVisible()
        ):
            return
        menu.show_for(button)
        self._schedule_page_menu_close(page_id)

    def _request_page_option(self, page_id: int, option: str) -> None:
        menu = self._page_menus.get(page_id)
        if menu is not None:
            menu.hide()
        self.set_page_option(page_id, option)
        self.page_option_requested.emit(page_id, option)


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
