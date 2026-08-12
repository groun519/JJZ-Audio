from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.widgets import (
    FeedbackButton,
    SvgIconButton,
    attach_transparent_scroll_widget,
    render_app_icon,
)
from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.services.i18n import tr


_CARD_WIDTH = 344
_CARD_MINIMUM_WIDTH = 180
_CARD_HEIGHT = 50
_POPUP_WIDTH = 460
_ROW_HEIGHT = 48


class NavigationWorkSongSelector(FeedbackButton):
    """Large work-song card with an application-themed selection popup."""

    song_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("NavigationWorkSongCard")
        self.setMinimumSize(_CARD_MINIMUM_WIDTH, _CARD_HEIGHT)
        self.setMaximumWidth(_CARD_WIDTH)
        self.setFixedHeight(_CARD_HEIGHT)
        self.resize(_CARD_WIDTH, _CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(tr("Select work song"))

        self._songs: tuple[tuple[str, str], ...] = ()
        self._selected_song_id = ""
        self._theme_mode = "white"
        self._loading = False
        self._suppress_popup_reopen = False
        self._loading_phase = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(45)
        self._loading_timer.timeout.connect(self._advance_loading_phase)

        self._popup = _WorkSongPopup(self)
        self._popup.song_selected.connect(self._activate_song)
        self._popup.closed.connect(self._on_popup_closed)
        self.clicked.connect(self.show_selector)
        self._update_tooltip()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_CARD_WIDTH, _CARD_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(_CARD_MINIMUM_WIDTH, _CARD_HEIGHT)

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str = "") -> None:
        self._songs = tuple((str(song_id), str(title)) for song_id, title in songs)
        valid_ids = {song_id for song_id, _title in self._songs}
        self._selected_song_id = selected_id if selected_id in valid_ids else ""
        self._popup.set_songs(self._songs, self._selected_song_id)
        self._update_tooltip()
        self.update()

    def select_song(self, song_id: str, *, emit: bool = False) -> None:
        selected_id = song_id if self.has_song(song_id) else ""
        changed = selected_id != self._selected_song_id
        self._selected_song_id = selected_id
        self._popup.select_song(selected_id)
        self._update_tooltip()
        self.update()
        if emit and changed:
            self.song_changed.emit(selected_id)

    def selected_song_id(self) -> str:
        return self._selected_song_id

    def has_song(self, song_id: str) -> bool:
        return any(candidate_id == song_id for candidate_id, _title in self._songs)

    def currentText(self) -> str:  # noqa: N802
        for song_id, title in self._songs:
            if song_id == self._selected_song_id:
                return title
        return tr("No work song")

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self._popup.set_theme_mode(theme_mode)
        self.update()

    def set_loading(self, is_loading: bool) -> None:
        is_loading = bool(is_loading)
        if self._loading == is_loading:
            return
        self._loading = is_loading
        if is_loading:
            self._loading_phase = 0
            self._loading_timer.start()
            self.setCursor(Qt.CursorShape.BusyCursor)
        else:
            self._loading_timer.stop()
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def is_loading(self) -> bool:
        return self._loading

    def apply_language(self) -> None:
        self.setAccessibleName(tr("Select work song"))
        self._popup.apply_language()
        self._update_tooltip()
        self.update()

    def show_selector(self) -> None:
        if self._suppress_popup_reopen:
            self._suppress_popup_reopen = False
            return
        if self._loading:
            return
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.set_songs(self._songs, self._selected_song_id)
        self._popup.show_for(self)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = _card_palette(
            self._theme_mode,
            selected=bool(self._selected_song_id),
            hovered=self._is_pointer_hovered() or self._popup.isVisible(),
            pressed=self._is_pointer_pressed() or self.isDown(),
            loading=self._loading,
        )
        card_rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setBrush(palette["background"])
        painter.setPen(QPen(palette["border"], 1.25))
        painter.drawRoundedRect(card_rect, 13, 13)

        icon_rect = QRectF(10, 8, 34, 34)
        painter.setBrush(palette["icon_background"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(icon_rect, 9, 9)
        render_app_icon(
            painter,
            icon_rect.adjusted(8, 8, -8, -8),
            "pin_filled" if self._selected_song_id else "pin",
            palette["accent"],
        )

        label_font = QFont(self.font())
        label_font.setPixelSize(9)
        label_font.setWeight(QFont.Weight.Bold)
        painter.setFont(label_font)
        painter.setPen(palette["label"])
        painter.drawText(
            QRectF(54, 7, max(0, self.width() - 92), 15),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            tr("WORKING") if self._loading else tr("WORK"),
        )

        title_font = QFont(self.font())
        title_font.setPixelSize(12)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(palette["title"])
        title_rect = QRectF(54, 21, max(0, self.width() - 92), 21)
        title = painter.fontMetrics().elidedText(
            self.currentText(),
            Qt.TextElideMode.ElideRight,
            int(title_rect.width()),
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )

        render_app_icon(
            painter,
            QRectF(self.width() - 30, 17, 16, 16),
            "chevron_down",
            palette["chevron"],
        )
        if self._loading:
            loading_pen = QPen(palette["loading"], 2)
            loading_pen.setDashPattern((4, 3))
            loading_pen.setDashOffset(-self._loading_phase / 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(loading_pen)
            painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), 12, 12)
        self._draw_keyboard_focus(painter, card_rect, 13)

    def _activate_song(self, song_id: str) -> None:
        self.select_song(song_id, emit=True)

    def _on_popup_closed(self, pointer_over_card: bool) -> None:
        self._suppress_popup_reopen = pointer_over_card
        if pointer_over_card:
            QTimer.singleShot(250, self._clear_popup_reopen_suppression)
        self.update()

    def _clear_popup_reopen_suppression(self) -> None:
        self._suppress_popup_reopen = False

    def _advance_loading_phase(self) -> None:
        self._loading_phase = (self._loading_phase + 1) % 64
        self.update()

    def _update_tooltip(self) -> None:
        self.setToolTip(self.currentText())


class _WorkSongPopup(QFrame):
    song_selected = Signal(str)
    closed = Signal(bool)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("NavigationWorkSongPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._theme_mode = "white"
        self._songs: tuple[tuple[str, str], ...] = ()
        self._selected_song_id = ""
        self._rows: list[_WorkSongPopupRow] = []

        self.header_label = QLabel()
        self.header_label.setObjectName("NavigationWorkSongPopupTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("NavigationWorkSongPopupCount")
        self.close_button = SvgIconButton("close", size=30)
        self.close_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.close_button, "Close")
        self.close_button.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        header.addWidget(self.header_label)
        header.addStretch(1)
        header.addWidget(self.count_label)
        header.addWidget(self.close_button)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("NavigationWorkSongSearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("NavigationWorkSongScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        attach_transparent_scroll_widget(self.scroll_area, self.rows_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.scroll_area, 1)
        self.apply_language()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.close_button.set_theme_mode(theme_mode)
        for row in self._rows:
            row.set_theme_mode(theme_mode)
        self.update()

    def set_songs(self, songs: Iterable[tuple[str, str]], selected_id: str) -> None:
        songs_tuple = tuple(songs)
        if songs_tuple != self._songs:
            self._songs = songs_tuple
            self._rebuild_rows()
        self.select_song(selected_id)
        self.count_label.setText(str(len(self._songs)))

    def select_song(self, song_id: str) -> None:
        self._selected_song_id = song_id
        for row in self._rows:
            row.set_selected(row.song_id == song_id)

    def apply_language(self) -> None:
        self.header_label.setText(tr("Select work song"))
        self.search_edit.setPlaceholderText(tr("Search songs"))
        set_translated_tooltip(self.close_button, "Close")
        for row in self._rows:
            if not row.song_id:
                row.set_title(tr("No work song"))

    def show_for(self, anchor: QWidget) -> None:
        self.search_edit.clear()
        visible_rows = min(len(self._rows), 6)
        popup_height = 106 + max(1, visible_rows) * (_ROW_HEIGHT + 4)
        self.resize(max(_POPUP_WIDTH, anchor.width()), min(430, popup_height))

        below = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = QApplication.screenAt(below) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        x = below.x()
        y = below.y()
        if available is not None:
            x = min(max(x, available.left() + 8), available.right() - self.width() - 8)
            if y + self.height() > available.bottom() - 8:
                y = anchor.mapToGlobal(QPoint(0, -self.height() - 6)).y()
        self.move(x, y)
        self.show()
        self.raise_()
        self.search_edit.setFocus(Qt.FocusReason.PopupFocusReason)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background, border = _popup_palette(self._theme_mode)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setBrush(background)
        painter.setPen(QPen(border, 1.25))
        painter.drawRoundedRect(rect, 15, 15)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        anchor = self.parentWidget()
        pointer_over_card = False
        if anchor is not None:
            local_position = anchor.mapFromGlobal(QCursor.pos())
            pointer_over_card = anchor.rect().contains(local_position)
        self.closed.emit(pointer_over_card)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _rebuild_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        entries = (("", tr("No work song")), *self._songs)
        for song_id, title in entries:
            row = _WorkSongPopupRow(song_id, title)
            row.set_theme_mode(self._theme_mode)
            row.clicked.connect(lambda _checked=False, value=song_id: self._choose(value))
            self.rows_layout.addWidget(row)
            self._rows.append(row)
        self.rows_layout.addStretch(1)
        self._apply_filter(self.search_edit.text())

    def _apply_filter(self, query: str) -> None:
        normalized = query.strip().casefold()
        for row in self._rows:
            row.setVisible(not normalized or normalized in row.title.casefold())

    def _choose(self, song_id: str) -> None:
        self.hide()
        self.song_selected.emit(song_id)


class _WorkSongPopupRow(FeedbackButton):
    def __init__(self, song_id: str, title: str) -> None:
        super().__init__()
        self.song_id = song_id
        self.title = title
        self._selected = False
        self._theme_mode = "white"
        self.setFixedHeight(_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_title(title)

    def set_title(self, title: str) -> None:
        self.title = title
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = _popup_row_palette(
            self._theme_mode,
            selected=self._selected,
            hovered=self._is_pointer_hovered(),
            pressed=self._is_pointer_pressed() or self.isDown(),
        )
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(palette["background"])
        painter.setPen(QPen(palette["border"], 1))
        painter.drawRoundedRect(rect, 10, 10)

        icon_size = 18
        icon_rect = QRectF(
            14,
            round((self.height() - icon_size) / 2),
            icon_size,
            icon_size,
        )
        render_app_icon(
            painter,
            icon_rect,
            "pin_filled" if self._selected else "pin",
            palette["icon"],
        )
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Bold if self._selected else QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(palette["title"])
        text_rect = QRectF(44, 0, max(0, self.width() - 58), self.height())
        title = painter.fontMetrics().elidedText(
            self.title,
            Qt.TextElideMode.ElideRight,
            int(text_rect.width()),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        self._draw_keyboard_focus(painter, rect, 10)


def _card_palette(
    theme_mode: str,
    *,
    selected: bool,
    hovered: bool,
    pressed: bool,
    loading: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        if selected or loading:
            background = "#332b20" if hovered else "#2b271f"
            if pressed:
                background = "#3b3021"
            return {
                "background": QColor(background),
                "border": QColor("#8a7148" if hovered or loading else "#66583d"),
                "icon_background": QColor("#453821"),
                "accent": QColor("#e8b26e"),
                "label": QColor("#cfaa75"),
                "title": QColor("#f2f0e9"),
                "chevron": QColor("#d5b27e"),
                "loading": QColor("#f0c27c"),
            }
        background = "#222220" if hovered else "#191918"
        if pressed:
            background = "#292927"
        return {
            "background": QColor(background),
            "border": QColor("#494945" if hovered else "#343431"),
            "icon_background": QColor("#282826"),
            "accent": QColor("#8d8a82"),
            "label": QColor("#85827a"),
            "title": QColor("#aaa7a0"),
            "chevron": QColor("#85827a"),
            "loading": QColor("#c7a46f"),
        }
    if selected or loading:
        background = "#f5ead5" if hovered else "#efe4cf"
        if pressed:
            background = "#e6d6b8"
        return {
            "background": QColor(background),
            "border": QColor("#b18b53" if hovered or loading else "#c8ad7d"),
            "icon_background": QColor("#e1cca5"),
            "accent": QColor("#714716"),
            "label": QColor("#806039"),
            "title": QColor("#201a12"),
            "chevron": QColor("#76562e"),
            "loading": QColor("#95672d"),
        }
    background = "#eee9df" if hovered else "#f7f4ed"
    if pressed:
        background = "#e4ded2"
    return {
        "background": QColor(background),
        "border": QColor("#bbb4a8" if hovered else "#d6d0c5"),
        "icon_background": QColor("#e9e4da"),
        "accent": QColor("#777168"),
        "label": QColor("#817b71"),
        "title": QColor("#5f5b54"),
        "chevron": QColor("#817b71"),
        "loading": QColor("#95672d"),
    }


def _popup_palette(theme_mode: str) -> tuple[QColor, QColor]:
    if theme_mode == "dark":
        return QColor("#181817"), QColor("#454540")
    return QColor("#f8f5ee"), QColor("#c9c2b6")


def _popup_row_palette(
    theme_mode: str,
    *,
    selected: bool,
    hovered: bool,
    pressed: bool,
) -> dict[str, QColor]:
    if theme_mode == "dark":
        background = QColor("#2b271f") if selected else QColor(0, 0, 0, 0)
        border = QColor("#66583d") if selected else QColor(0, 0, 0, 0)
        if hovered:
            background = QColor("#292927" if not selected else "#352d20")
            border = QColor("#494945" if not selected else "#8a7148")
        if pressed:
            background = QColor("#343431")
        return {
            "background": background,
            "border": border,
            "icon": QColor("#e8b26e" if selected else "#77746d"),
            "title": QColor("#f1efe9" if selected else "#c6c3bc"),
        }
    background = QColor("#efe4cf") if selected else QColor(0, 0, 0, 0)
    border = QColor("#c8ad7d") if selected else QColor(0, 0, 0, 0)
    if hovered:
        background = QColor("#ebe6dc" if not selected else "#f5ead5")
        border = QColor("#c9c2b6" if not selected else "#b18b53")
    if pressed:
        background = QColor("#dfd8cc")
    return {
        "background": background,
        "border": border,
        "icon": QColor("#714716" if selected else "#807a70"),
        "title": QColor("#201a12" if selected else "#48443d"),
    }
