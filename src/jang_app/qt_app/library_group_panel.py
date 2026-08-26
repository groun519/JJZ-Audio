from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from jang_app.qt_app.localization import set_translated_tooltip
from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.i18n import tr
from jang_app.services.library_groups import (
    ALL_SONGS_GROUP_ID,
    UNGROUPED_SONGS_GROUP_ID,
    LibraryGroup,
)


_GROUP_ID_ROLE = Qt.ItemDataRole.UserRole
_PARENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class _SongGroupTree(QTreeWidget):
    songs_move_requested = Signal(tuple, object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LibraryGroupTree")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setRootIsDecorated(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAllColumnsShowFocus(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if isinstance(event.source(), QListWidget):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if isinstance(event.source(), QListWidget) and self._drop_group_id(event.position().toPoint()) != ALL_SONGS_GROUP_ID:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        source = event.source()
        if not isinstance(source, QListWidget):
            event.ignore()
            return
        group_id = self._drop_group_id(event.position().toPoint())
        if group_id == ALL_SONGS_GROUP_ID:
            event.ignore()
            return
        song_ids = tuple(
            str(item.data(Qt.ItemDataRole.UserRole) or "")
            for item in source.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        )
        if not song_ids:
            event.ignore()
            return
        target_id = None if group_id == UNGROUPED_SONGS_GROUP_ID else group_id
        self.songs_move_requested.emit(song_ids, target_id)
        event.acceptProposedAction()

    def _drop_group_id(self, position) -> str:
        item = self.itemAt(position)
        return str(item.data(0, _GROUP_ID_ROLE)) if item is not None else ALL_SONGS_GROUP_ID


class LibraryGroupPanel(QFrame):
    group_selected = Signal(str)
    create_requested = Signal(object)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    songs_move_requested = Signal(tuple, object)
    move_selection_requested = Signal(object)
    expanded_groups_changed = Signal(tuple)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LibraryGroupPanel")
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 12, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 2, 0)
        header.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setObjectName("LibraryGroupTitle")
        self.add_button = SvgIconButton("file_plus", size=30)
        self.add_button.setObjectName("LibraryGroupAddButton")
        self.add_button.clicked.connect(lambda: self.create_requested.emit(None))
        header.addWidget(self.title_label, 1)
        header.addWidget(self.add_button, 0)

        self.tree = _SongGroupTree()
        self.tree.itemSelectionChanged.connect(self._emit_selection)
        self.tree.itemExpanded.connect(lambda _item: self._emit_expanded_groups())
        self.tree.itemCollapsed.connect(lambda _item: self._emit_expanded_groups())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        self.tree.songs_move_requested.connect(self.songs_move_requested)

        layout.addLayout(header)
        layout.addWidget(self.tree, 1)
        self.apply_language()

    def set_groups(
        self,
        groups: Iterable[LibraryGroup],
        counts: Mapping[str, int],
        selected_group_id: str,
        expanded_group_ids: Iterable[str],
    ) -> None:
        group_list = tuple(groups)
        expanded = frozenset(expanded_group_ids)
        with QSignalBlocker(self.tree):
            self.tree.clear()
            all_item = self._create_item(
                tr("All Songs"),
                ALL_SONGS_GROUP_ID,
                counts.get(ALL_SONGS_GROUP_ID, 0),
            )
            self.tree.addTopLevelItem(all_item)

            items_by_id: dict[str, QTreeWidgetItem] = {
                group.group_id: self._create_item(
                    group.name,
                    group.group_id,
                    counts.get(group.group_id, 0),
                    group.parent_group_id,
                )
                for group in group_list
            }
            for group in group_list:
                item = items_by_id[group.group_id]
                parent = items_by_id.get(group.parent_group_id or "")
                if parent is not None:
                    parent.addChild(item)
                else:
                    self.tree.addTopLevelItem(item)

            ungrouped_item = self._create_item(
                tr("Ungrouped"),
                UNGROUPED_SONGS_GROUP_ID,
                counts.get(UNGROUPED_SONGS_GROUP_ID, 0),
            )
            self.tree.addTopLevelItem(ungrouped_item)
            for group_id in expanded:
                item = items_by_id.get(group_id)
                if item is not None:
                    item.setExpanded(True)

            selected_item = self._find_item(selected_group_id) or all_item
            self.tree.setCurrentItem(selected_item)

    def selected_group_id(self) -> str:
        item = self.tree.currentItem()
        return str(item.data(0, _GROUP_ID_ROLE)) if item is not None else ALL_SONGS_GROUP_ID

    def expanded_group_ids(self) -> tuple[str, ...]:
        expanded = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            self._collect_expanded(item, expanded)
        return tuple(expanded)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Groups"))
        set_translated_tooltip(self.add_button, "New Group")

    def set_theme_mode(self, theme_mode: str) -> None:
        self.add_button.set_theme_mode(theme_mode)
        tokens = theme_tokens(theme_mode)
        palette = self.tree.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["selection"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens["text"]))
        self.tree.setPalette(palette)

    @staticmethod
    def _create_item(
        label: str,
        group_id: str,
        count: int,
        parent_group_id: str | None = None,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem((label, str(count)))
        item.setData(0, _GROUP_ID_ROLE, group_id)
        item.setData(0, _PARENT_ID_ROLE, parent_group_id)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _emit_selection(self) -> None:
        self.group_selected.emit(self.selected_group_id())

    def _emit_expanded_groups(self) -> None:
        self.expanded_groups_changed.emit(self.expanded_group_ids())

    def _open_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        group_id = str(item.data(0, _GROUP_ID_ROLE))
        parent_group_id = item.data(0, _PARENT_ID_ROLE)
        menu = QMenu(self)

        if group_id == ALL_SONGS_GROUP_ID:
            menu.addAction(tr("New Group"), lambda: self.create_requested.emit(None))
        elif group_id == UNGROUPED_SONGS_GROUP_ID:
            menu.addAction(
                tr("Move selected songs here"),
                lambda: self.move_selection_requested.emit(None),
            )
        else:
            if parent_group_id is None:
                menu.addAction(
                    tr("New Subgroup"),
                    lambda: self.create_requested.emit(group_id),
                )
            menu.addAction(
                tr("Move selected songs here"),
                lambda: self.move_selection_requested.emit(group_id),
            )
            menu.addSeparator()
            menu.addAction(tr("Rename Group"), lambda: self.rename_requested.emit(group_id))
            menu.addAction(tr("Delete Group"), lambda: self.delete_requested.emit(group_id))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _find_item(self, group_id: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            found = self._find_in_branch(self.tree.topLevelItem(index), group_id)
            if found is not None:
                return found
        return None

    @classmethod
    def _find_in_branch(cls, item: QTreeWidgetItem, group_id: str) -> QTreeWidgetItem | None:
        if str(item.data(0, _GROUP_ID_ROLE)) == group_id:
            return item
        for index in range(item.childCount()):
            found = cls._find_in_branch(item.child(index), group_id)
            if found is not None:
                return found
        return None

    @classmethod
    def _collect_expanded(cls, item: QTreeWidgetItem, output: list[str]) -> None:
        group_id = str(item.data(0, _GROUP_ID_ROLE))
        if item.isExpanded() and group_id not in {ALL_SONGS_GROUP_ID, UNGROUPED_SONGS_GROUP_ID}:
            output.append(group_id)
        for index in range(item.childCount()):
            cls._collect_expanded(item.child(index), output)
