from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.theme import theme_tokens
from jang_app.qt_app.vocal_result_labels import display_compact_result_timestamp
from jang_app.qt_app.widgets import DangerIconButton, attach_transparent_scroll_widget
from jang_app.services.i18n import tr
from jang_app.services.vocal_split import VocalSplitRun


class VocalSplitGroupList(QFrame):
    """Vocal work groups created from the selected separation result."""

    group_selected = Signal(object)
    remove_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocalSplitGroupList")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(250)
        self._groups: tuple[VocalSplitRun, ...] = ()
        self._rows: dict[str, _VocalSplitGroupRow] = {}
        self._selected_group_id = ""
        self._theme_mode = "white"

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("VocalSplitGroupCount")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)

        self.content = QWidget()
        self.content.setObjectName("VocalSplitGroupContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("VocalSplitGroupEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("VocalSplitGroupScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        attach_transparent_scroll_widget(self.scroll, self.content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.scroll, 1)

        self.apply_language()
        self.set_theme_mode(self._theme_mode)
        self.set_groups(())

    def set_groups(
        self,
        groups: tuple[VocalSplitRun, ...],
        selected_group_id: str | None = None,
    ) -> VocalSplitRun | None:
        previous_group_id = self._selected_group_id
        available_ids = {group.run_id for group in groups}
        requested_group_id = selected_group_id or ""
        self._groups = groups
        self._selected_group_id = (
            requested_group_id
            if requested_group_id in available_ids
            else previous_group_id
            if previous_group_id in available_ids
            else groups[0].run_id
            if groups
            else ""
        )
        self._rebuild_rows()
        return self.selected_group()

    def selected_group(self) -> VocalSplitRun | None:
        return next(
            (group for group in self._groups if group.run_id == self._selected_group_id),
            None,
        )

    def select_group(self, run_id: str) -> bool:
        group = next((item for item in self._groups if item.run_id == run_id), None)
        if group is None:
            return False
        self._select_group(group, emit=False)
        return True

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        tokens = theme_tokens(theme_mode)
        self.setStyleSheet(_group_list_stylesheet(tokens))
        for row in self._rows.values():
            row.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Vocal Groups"))
        self.empty_label.setText(tr("No vocal groups yet"))
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                if widget is not self.empty_label:
                    widget.deleteLater()
        self._rows.clear()
        self.count_label.setText(str(len(self._groups)))
        if not self._groups:
            self.empty_label.show()
            self.content_layout.addWidget(self.empty_label, 1)
            return
        self.empty_label.hide()
        for group in self._groups:
            row = _VocalSplitGroupRow(group)
            row.set_selected(group.run_id == self._selected_group_id)
            row.set_theme_mode(self._theme_mode)
            row.activated.connect(self._select_group)
            row.remove_requested.connect(self.remove_requested.emit)
            self._rows[group.run_id] = row
            self.content_layout.addWidget(row)
        self.content_layout.addStretch(1)

    def _select_group(self, group: VocalSplitRun, *, emit: bool = True) -> None:
        if group.run_id == self._selected_group_id:
            for run_id, row in self._rows.items():
                row.set_selected(run_id == group.run_id)
            return
        self._selected_group_id = group.run_id
        for run_id, row in self._rows.items():
            row.set_selected(run_id == group.run_id)
        if emit:
            self.group_selected.emit(group)


class _VocalSplitGroupRow(QFrame):
    activated = Signal(object)
    remove_requested = Signal(object)

    def __init__(self, group: VocalSplitRun) -> None:
        super().__init__()
        self.group = group
        self.setObjectName("VocalSplitGroupRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(76)
        self._selected = False

        timestamp = display_compact_result_timestamp(group.created_at)
        self.title_label = QLabel(
            f"{tr('Vocal group')}  /  {timestamp}" if timestamp else tr("Vocal group")
        )
        self.title_label.setObjectName("VocalSplitGroupTitle")
        self.meta_label = QLabel(
            f"{tr('{count} vocals', count=len(group.stems))}"
            f"  /  {tr('{count} splits', count=len(group.operations))}"
        )
        self.meta_label.setObjectName("VocalSplitGroupMeta")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(4)
        labels.addWidget(self.title_label)
        labels.addWidget(self.meta_label)

        self.remove_button = DangerIconButton(size=28)
        self.remove_button.setToolTip(tr("Remove this vocal split"))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.group))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 11, 10, 11)
        layout.setSpacing(8)
        layout.addLayout(labels, 1)
        layout.addWidget(self.remove_button)
        self.setToolTip(str(group.input_path))
        self._sync_remove_visibility()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_remove_visibility()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.remove_button.set_theme_mode(theme_mode)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._sync_remove_visibility(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._sync_remove_visibility(hovered=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.group)
        super().mouseReleaseEvent(event)

    def _sync_remove_visibility(self, *, hovered: bool | None = None) -> None:
        is_hovered = self.underMouse() if hovered is None else hovered
        self.remove_button.setVisible(is_hovered)


def _group_list_stylesheet(tokens: dict[str, str]) -> str:
    return f"""
        QFrame#VocalSplitGroupList {{
            background: {tokens['surface']};
            border: 1px solid {tokens['border']};
            border-radius: 14px;
        }}
        QWidget#VocalSplitGroupContent,
        QScrollArea#VocalSplitGroupScroll {{
            background: transparent;
            border: none;
        }}
        QFrame#VocalSplitGroupRow {{
            background: {tokens['card']};
            border: 1px solid {tokens['border']};
            border-radius: 9px;
        }}
        QFrame#VocalSplitGroupRow:hover {{
            background: {tokens['hover']};
            border-color: {tokens['button_border']};
        }}
        QFrame#VocalSplitGroupRow[selected="true"] {{
            background: {tokens['pair_background']};
            border: 1px solid {tokens['pair_border']};
        }}
        QLabel#VocalSplitGroupTitle {{
            color: {tokens['text']};
            font-weight: 700;
            border: none;
            background: transparent;
        }}
        QLabel#VocalSplitGroupMeta,
        QLabel#VocalSplitGroupCount,
        QLabel#VocalSplitGroupEmpty {{
            color: {tokens['muted']};
            border: none;
            background: transparent;
        }}
        QLabel#VocalSplitGroupMeta {{
            font-size: 10px;
        }}
        QLabel#VocalSplitGroupEmpty {{
            padding: 28px 8px;
        }}
    """
