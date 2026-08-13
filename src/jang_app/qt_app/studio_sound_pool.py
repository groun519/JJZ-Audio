from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.vocal_result_labels import (
    vocal_take_card_detail,
    vocal_take_label,
    vocal_take_tooltip,
)
from jang_app.qt_app.waveform_thumbnail import WaveformThumbnail
from jang_app.qt_app.widgets import (
    COMPACT_ICON_BUTTON_SIZE,
    DangerIconButton,
    FeedbackButton,
    SvgIconButton,
    attach_transparent_scroll_widget,
)
from jang_app.services.i18n import tr
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import TRACK_VIDEO


STUDIO_ASSET_MIME = "application/x-jjzero-studio-asset"
_ALL_ROLES = "all"
_GRID_CARD_MIN_WIDTH = 172
_GRID_SPACING = 10


class StudioSoundCard(SoundPoolItemCard):
    selected = Signal(str)
    remove_requested = Signal(object)

    def __init__(self, asset: StudioSoundAsset, parent: QWidget | None = None) -> None:
        self.asset = asset
        source, detail = _asset_description(asset)
        role = asset.reference.role
        title = _studio_card_title(asset, source)
        super().__init__(
            asset.asset_id,
            role=role,
            path=asset.path,
            title=title,
            badge=_short_role_label(role),
            detail=_studio_card_detail(asset, source, detail),
            duration_ms=asset.clip_duration_ms,
            media_kind=asset.media_kind,
            object_name="StudioSoundCard",
            parent=parent,
        )
        self.remove_button: DangerIconButton | None = None
        if asset.can_remove:
            self.remove_button = DangerIconButton(size=28)
            self.remove_button.clicked.connect(
                lambda: self.remove_requested.emit(self.asset)
            )
            self.set_action_widget(self.remove_button)
        self._drag_origin = QPoint()
        self.activated.connect(self.selected.emit)
        self.apply_language()

    def apply_language(self) -> None:
        source, detail = _asset_description(self.asset)
        role = self.asset.reference.role
        self.set_content(
            title=_studio_card_title(self.asset, source),
            badge=_short_role_label(role),
            detail=_studio_card_detail(self.asset, source, detail),
            duration_ms=self.asset.clip_duration_ms,
            list_category=_studio_list_category(self.asset, source),
            list_name=_studio_list_name(self.asset, source, detail),
        )
        self.setToolTip(_asset_tooltip(self.asset))
        if self.remove_button is not None:
            self.remove_button.setToolTip(tr("Remove"))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        distance = (event.position().toPoint() - self._drag_origin).manhattanLength()
        if not event.buttons() & Qt.MouseButton.LeftButton or distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        mime = QMimeData()
        mime.setData(STUDIO_ASSET_MIME, self.asset.asset_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

class StudioSoundPool(QFrame):
    remove_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StudioSoundPool")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(220)
        self.setMaximumWidth(680)
        self._assets: tuple[StudioSoundAsset, ...] = ()
        self._cards: dict[str, StudioSoundCard] = {}
        self._selected_asset_id = ""
        self._theme_mode = "white"
        self._list_mode = False
        self._selected_role = _ALL_ROLES

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("StudioSoundCount")

        self.grid_button = SvgIconButton("grid", size=COMPACT_ICON_BUTTON_SIZE)
        self.grid_button.setObjectName("SoundPoolViewButton")
        self.grid_button.setCheckable(True)
        self.list_button = SvgIconButton("list", size=COMPACT_ICON_BUTTON_SIZE)
        self.list_button.setObjectName("SoundPoolViewButton")
        self.list_button.setCheckable(True)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.grid_button)
        self.view_group.addButton(self.list_button)
        self.grid_button.setChecked(True)
        self.grid_button.clicked.connect(lambda: self._set_list_mode(False))
        self.list_button.clicked.connect(lambda: self._set_list_mode(True))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        header.addWidget(self.grid_button)
        header.addWidget(self.list_button)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("StudioSoundSearch")
        self.search_edit.textChanged.connect(lambda _text: self._rebuild_layout())

        self.role_filter = QFrame()
        self.role_filter.setObjectName("StudioSoundRoleFilter")
        self.role_group = QButtonGroup(self)
        self.role_group.setExclusive(True)
        self.role_buttons: dict[str, FeedbackButton] = {}
        role_filter_layout = QHBoxLayout(self.role_filter)
        role_filter_layout.setContentsMargins(2, 2, 2, 2)
        role_filter_layout.setSpacing(1)
        for role in (
            _ALL_ROLES,
            "original_vocal",
            "instrumental",
            "converted_vocal",
            TRACK_VIDEO,
        ):
            button = FeedbackButton()
            button.setObjectName("StudioSoundRoleButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=role: self._set_role_filter(value))
            self.role_group.addButton(button)
            self.role_buttons[role] = button
            role_filter_layout.addWidget(button)
        self.role_buttons[_ALL_ROLES].setChecked(True)

        filters = QVBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(6)
        filters.addWidget(self.search_edit)
        filters.addWidget(self.role_filter)

        self.content = QWidget()
        self.content.setObjectName("StudioSoundPoolContent")
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(_GRID_SPACING)
        self.grid.setVerticalSpacing(_GRID_SPACING)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("StudioSoundEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("StudioSoundPoolScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        attach_transparent_scroll_widget(self.scroll, self.content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self.scroll, 1)

        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._rebuild_layout)
        self.apply_language()

    def set_assets(self, assets: tuple[StudioSoundAsset, ...]) -> None:
        if assets == self._assets:
            return
        previous_cards = self._cards
        self._assets = assets
        self._take_layout_items()
        next_cards: dict[str, StudioSoundCard] = {}
        for asset in assets:
            card = previous_cards.pop(asset.asset_id, None)
            if card is None or card.asset != asset:
                if card is not None:
                    card.hide()
                    card.deleteLater()
                card = self._create_card(asset)
            next_cards[asset.asset_id] = card
        for card in previous_cards.values():
            card.hide()
            card.deleteLater()
        self._cards = next_cards
        if self._selected_asset_id not in self._cards:
            self._selected_asset_id = ""
        self._rebuild_layout()

    def _create_card(self, asset: StudioSoundAsset) -> StudioSoundCard:
        card = StudioSoundCard(asset, self.content)
        card.selected.connect(self._select_asset)
        card.remove_requested.connect(self.remove_requested.emit)
        card.set_theme_mode(self._theme_mode)
        card.set_list_mode(self._list_mode)
        return card

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for button in (self.grid_button, self.list_button):
            button.set_theme_mode(theme_mode)
        for card in self._cards.values():
            card.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Sound Pool"))
        self.search_edit.setPlaceholderText(tr("Search sounds"))
        labels = {
            _ALL_ROLES: tr("All"),
            "original_vocal": tr("Vocal"),
            "instrumental": tr("Inst."),
            "converted_vocal": tr("RVC"),
            TRACK_VIDEO: tr("Media"),
        }
        for role, button in self.role_buttons.items():
            button.setText(labels[role])
            button.setToolTip(tr("All sounds") if role == _ALL_ROLES else tr(_role_label(role)))
        self.grid_button.setToolTip(tr("Grid view"))
        self.list_button.setToolTip(tr("List view"))
        self.empty_label.setText(tr("No sounds match the current filter."))
        for card in self._cards.values():
            card.apply_language()
        self._rebuild_layout()

    def visible_asset_ids(self) -> tuple[str, ...]:
        return tuple(card.asset.asset_id for card in self._visible_cards())

    def column_count(self) -> int:
        return self._column_count()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_layout()

    def _set_list_mode(self, enabled: bool) -> None:
        self._list_mode = bool(enabled)
        self.grid_button.setChecked(not enabled)
        self.list_button.setChecked(enabled)
        for card in self._cards.values():
            card.set_list_mode(enabled)
        self._rebuild_layout()

    def _set_role_filter(self, role: str) -> None:
        self._selected_role = role if role in self.role_buttons else _ALL_ROLES
        self.role_buttons[self._selected_role].setChecked(True)
        self._rebuild_layout()

    def _select_asset(self, asset_id: str) -> None:
        if asset_id == self._selected_asset_id:
            return
        previous = self._cards.get(self._selected_asset_id)
        if previous is not None:
            previous.set_selected(False)
        self._selected_asset_id = asset_id
        selected = self._cards.get(asset_id)
        if selected is not None:
            selected.set_selected(True)

    def _schedule_layout(self) -> None:
        self._layout_timer.start(0)

    def _visible_cards(self) -> list[StudioSoundCard]:
        query = self.search_edit.text().strip().casefold()
        role = self._selected_role
        cards: list[StudioSoundCard] = []
        for asset in self._assets:
            card = self._cards.get(asset.asset_id)
            if card is None or role != _ALL_ROLES and asset.reference.role != role:
                continue
            take_label = vocal_take_label(asset.take, asset.path)
            haystack = (
                f"{asset.label} {take_label} {asset.path.name} "
                f"{tr(_role_label(asset.reference.role))}"
            ).casefold()
            if query and query not in haystack:
                continue
            cards.append(card)
        return cards

    def _column_count(self) -> int:
        if self._list_mode:
            return 1
        available = max(1, self.scroll.viewport().width())
        return max(1, min(4, (available + _GRID_SPACING) // (_GRID_CARD_MIN_WIDTH + _GRID_SPACING)))

    def _rebuild_layout(self) -> None:
        self._take_layout_items()
        visible = self._visible_cards()
        columns = self._column_count()
        for index, card in enumerate(visible):
            card.set_list_mode(self._list_mode)
            card.setVisible(True)
            self.grid.addWidget(card, index // columns, index % columns)
        for card in self._cards.values():
            if card not in visible:
                card.hide()
        self.empty_label.setVisible(not visible)
        if not visible:
            self.grid.addWidget(self.empty_label, 0, 0, 1, max(1, columns))
        for column in range(4):
            self.grid.setColumnStretch(column, 0)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        visible_count = len(visible)
        total_count = len(self._assets)
        self.count_label.setText(
            str(total_count) if visible_count == total_count else f"{visible_count} / {total_count}"
        )

    def _take_layout_items(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()


def _role_label(role: str) -> str:
    return {
        "original_vocal": "Original Vocal",
        "instrumental": "Instrumental",
        "converted_vocal": "Converted Vocal",
        TRACK_VIDEO: "Media",
    }.get(role, "Audio")


def _asset_description(asset: StudioSoundAsset) -> tuple[str, str]:
    parts = [part.strip() for part in asset.label.split("/") if part.strip()]
    source = parts[0] if parts else tr("Sound")
    detail = " / ".join(parts[1:]) if len(parts) > 1 else asset.path.stem
    role_name = tr(_role_label(asset.reference.role))
    if detail.casefold() in {role_name.casefold(), _role_label(asset.reference.role).casefold()}:
        detail = asset.path.stem
    return source, detail


def _studio_card_title(asset: StudioSoundAsset, source: str) -> str:
    if asset.reference.role == "converted_vocal":
        return vocal_take_label(asset.take, asset.path)
    if asset.media_kind in {"video", "image"}:
        return tr(source)
    return tr(source)


def _studio_card_detail(
    asset: StudioSoundAsset,
    source: str,
    detail: str,
) -> str:
    if asset.reference.role == "converted_vocal":
        return vocal_take_card_detail(asset.take, source)
    return tr(detail)


def _studio_list_category(asset: StudioSoundAsset, source: str) -> str:
    if asset.media_kind == "image":
        return tr("Image")
    if asset.media_kind == "video":
        return tr("Video")
    return tr(source)


def _studio_list_name(
    asset: StudioSoundAsset,
    source: str,
    detail: str,
) -> str:
    if asset.reference.role == "converted_vocal":
        return vocal_take_label(asset.take, asset.path)
    if asset.media_kind in {"video", "image"}:
        return _studio_card_title(asset, source)
    return tr(detail)


def _asset_tooltip(asset: StudioSoundAsset) -> str:
    source, _detail = _asset_description(asset)
    if asset.reference.role != "converted_vocal":
        return f"{tr(source)}\n{asset.path}"
    return f"{tr(source)}\n{vocal_take_tooltip(asset.take, asset.path)}"


def _short_role_label(role: str) -> str:
    return {
        "original_vocal": tr("Vocal"),
        "instrumental": tr("Inst."),
        "converted_vocal": tr("RVC"),
        TRACK_VIDEO: tr("Media"),
    }.get(role, tr("Audio"))


def _format_time(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"
