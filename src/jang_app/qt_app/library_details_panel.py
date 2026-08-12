from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.config import SUPPORTED_AUDIO_EXTENSIONS
from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.segmented_stack import SegmentedStack
from jang_app.qt_app.transport_controls import TransportControls
from jang_app.qt_app.widgets import DangerIconButton, SvgIconButton
from jang_app.services.song_assets import (
    STAGE_EXPORT,
    STAGE_SOURCE,
    STAGE_STUDIO,
    STAGE_VOCAL,
    SongAsset,
    SongAssetDetails,
)


class LibraryDetailsPanel(QFrame):
    back_requested = Signal()
    open_location_requested = Signal(object)
    remove_asset_requested = Signal(str, object)
    remove_assets_requested = Signal(str, object)
    preview_requested = Signal(object)
    preview_play_toggled = Signal(object)
    preview_seek_requested = Signal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._details: SongAssetDetails | None = None
        self._theme_mode = "white"

        self.back_button = SvgIconButton("arrow_left", size=34)
        self.back_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.back_button, "Back to library")
        self.back_button.clicked.connect(self.back_requested.emit)

        self.title_label = QLabel("Song Details")
        self.title_label.setObjectName("LibraryDetailTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.source_badge = QLabel("LOCAL")
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(72)

        self.open_package_button = SvgIconButton("folder", size=34)
        self.open_package_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_package_button, "Open song data location")
        self.open_package_button.clicked.connect(self._open_package_location)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.back_button, 0)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.source_badge, 0)
        header.addWidget(self.open_package_button, 0)

        self.metadata_label = QLabel("")
        self.metadata_label.setObjectName("LibraryDetailMeta")
        self.metadata_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.metadata_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.source_page = _AssetStagePage()
        self.vocal_page = _AssetStagePage()
        self.studio_page = _AssetStagePage()
        self.export_page = _AssetStagePage()
        self.stage_pages = {
            STAGE_SOURCE: self.source_page,
            STAGE_VOCAL: self.vocal_page,
            STAGE_STUDIO: self.studio_page,
            STAGE_EXPORT: self.export_page,
        }
        for page in self.stage_pages.values():
            page.open_location_requested.connect(self.open_location_requested.emit)
            page.remove_asset_requested.connect(self._request_asset_removal)
            page.remove_assets_requested.connect(self._request_assets_removal)
            page.preview_requested.connect(self.preview_requested.emit)
            page.preview_play_toggled.connect(self.preview_play_toggled.emit)
            page.preview_seek_requested.connect(self.preview_seek_requested.emit)

        self.stage_stack = SegmentedStack(
            (
                ("Source", self.source_page),
                ("Vocal", self.vocal_page),
                ("Studio", self.studio_page),
                ("Export", self.export_page),
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self.metadata_label, 0)
        layout.addWidget(self.stage_stack, 1)
        self.clear()

    @property
    def song_id(self) -> str:
        return self._details.song_id if self._details is not None else ""

    def set_details(self, details: SongAssetDetails) -> None:
        self._details = details
        self.title_label.setText(details.title)
        source_label = _source_label(details.source_type)
        set_translated_text(self.source_badge, source_label)
        self.source_badge.setProperty("sourceType", details.source_type)
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)

        metadata = [details.original_name or details.package_dir.name]
        if details.source_url:
            metadata.append(details.source_url)
        created_at = _format_timestamp(details.created_at)
        if created_at:
            metadata.append(created_at)
        self.metadata_label.setText("  /  ".join(metadata))
        self.metadata_label.setToolTip(f"{details.package_dir}\n{details.source_url}".rstrip())
        self.open_package_button.setEnabled(True)

        for stage, page in self.stage_pages.items():
            page.set_assets(details.assets_for(stage), self._theme_mode)

    def clear(self) -> None:
        self._details = None
        set_translated_text(self.title_label, "Song Details")
        self.metadata_label.clear()
        self.open_package_button.setEnabled(False)
        for page in self.stage_pages.values():
            page.set_assets((), self._theme_mode)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.back_button.set_theme_mode(theme_mode)
        self.open_package_button.set_theme_mode(theme_mode)
        for page in self.stage_pages.values():
            page.set_theme_mode(theme_mode)

    def set_preview_expanded(self, path: Path | None, is_expanded: bool) -> None:
        for page in self.stage_pages.values():
            page.set_preview_expanded(path, is_expanded)

    def set_preview_queue(self, path: Path, duration_ms: int) -> None:
        row = self._asset_row(path)
        if row is not None:
            row.set_preview_queue(duration_ms)

    def set_preview_position(self, path: Path, position_ms: int, duration_ms: int) -> None:
        row = self._asset_row(path)
        if row is not None:
            row.set_preview_position(position_ms, duration_ms)

    def set_preview_playing(self, path: Path, is_playing: bool) -> None:
        row = self._asset_row(path)
        if row is not None:
            row.set_preview_playing(is_playing)

    def clear_preview(self) -> None:
        for page in self.stage_pages.values():
            page.clear_preview()

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.back_button, "Back to library")
        set_translated_tooltip(self.open_package_button, "Open song data location")
        for page in self.stage_pages.values():
            page.apply_language()

    def _open_package_location(self) -> None:
        if self._details is not None:
            self.open_location_requested.emit(self._details.package_dir)

    def _request_asset_removal(self, asset: SongAsset) -> None:
        if self._details is not None:
            self.remove_asset_requested.emit(self._details.song_id, asset)

    def _request_assets_removal(self, assets: tuple[SongAsset, ...]) -> None:
        if self._details is not None and assets:
            self.remove_assets_requested.emit(self._details.song_id, assets)

    def _asset_row(self, path: Path) -> _SongAssetRow | None:
        for page in self.stage_pages.values():
            row = page.asset_row(path)
            if row is not None:
                return row
        return None


class _AssetStagePage(QWidget):
    open_location_requested = Signal(object)
    remove_asset_requested = Signal(object)
    remove_assets_requested = Signal(object)
    preview_requested = Signal(object)
    preview_play_toggled = Signal(object)
    preview_seek_requested = Signal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self._theme_mode = "white"
        self.asset_rows: list[_SongAssetRow] = []

        self.summary_label = QLabel("0 files")
        self.summary_label.setObjectName("LibraryStageSummary")

        self.selection_mode_button = SvgIconButton("list", size=30)
        self.selection_mode_button.setObjectName("LibraryAssetSelectionModeButton")
        self.selection_mode_button.setCheckable(True)
        set_translated_tooltip(self.selection_mode_button, "Select multiple files")
        self.selection_mode_button.toggled.connect(self._set_selection_mode)

        self.selected_count_label = QLabel()
        self.selected_count_label.setObjectName("LibraryAssetSelectedCount")
        self.selected_count_label.hide()

        self.bulk_remove_button = DangerIconButton(size=30)
        set_translated_tooltip(self.bulk_remove_button, "Delete selected files")
        self.bulk_remove_button.clicked.connect(self._request_bulk_removal)
        self.bulk_remove_button.hide()

        summary_layout = QHBoxLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        summary_layout.addWidget(self.summary_label, 0)
        summary_layout.addWidget(self.selection_mode_button, 0)
        summary_layout.addWidget(self.selected_count_label, 0)
        summary_layout.addWidget(self.bulk_remove_button, 0)
        summary_layout.addStretch(1)

        self.asset_content = QWidget()
        self.asset_content.setObjectName("LibraryAssetContent")
        self.asset_layout = QVBoxLayout(self.asset_content)
        self.asset_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_layout.setSpacing(8)

        self.asset_scroll = QScrollArea()
        self.asset_scroll.setObjectName("LibraryAssetScroll")
        self.asset_scroll.viewport().setObjectName("LibraryAssetViewport")
        self.asset_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.asset_scroll.setWidgetResizable(True)
        self.asset_scroll.setWidget(self.asset_content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(summary_layout)
        layout.addWidget(self.asset_scroll, 1)

    def set_assets(self, assets: tuple[SongAsset, ...], theme_mode: str) -> None:
        self._set_selection_mode(False)
        self._clear_rows()
        self._theme_mode = theme_mode
        set_translated_text(self.summary_label, "{count} files", count=len(assets))
        self.selection_mode_button.setEnabled(any(asset.can_remove for asset in assets))
        if not assets:
            empty_label = QLabel()
            set_translated_text(empty_label, "No assets in this stage.")
            empty_label.setObjectName("LibraryEmptyState")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.asset_layout.addWidget(empty_label, 1)
            return

        for asset in assets:
            row = _SongAssetRow(asset)
            row.set_theme_mode(theme_mode)
            row.open_location_requested.connect(self.open_location_requested.emit)
            row.remove_requested.connect(self.remove_asset_requested.emit)
            row.selection_changed.connect(self._update_selection_state)
            row.preview_requested.connect(self.preview_requested.emit)
            row.preview_play_toggled.connect(self.preview_play_toggled.emit)
            row.preview_seek_requested.connect(self.preview_seek_requested.emit)
            self.asset_rows.append(row)
            self.asset_layout.addWidget(row, 0)
        self.asset_layout.addStretch(1)
        self._update_selection_state()

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.selection_mode_button.set_theme_mode(theme_mode)
        self.bulk_remove_button.set_theme_mode(theme_mode)
        for row in self.asset_rows:
            row.set_theme_mode(theme_mode)

    def set_preview_expanded(self, path: Path | None, is_expanded: bool) -> None:
        for row in self.asset_rows:
            row.set_preview_expanded(
                bool(is_expanded and path is not None and _same_path(row.asset.path, path))
            )

    def clear_preview(self) -> None:
        for row in self.asset_rows:
            row.set_preview_expanded(False)
            row.clear_preview()

    def asset_row(self, path: Path) -> _SongAssetRow | None:
        return next(
            (row for row in self.asset_rows if _same_path(row.asset.path, path)),
            None,
        )

    def apply_language(self) -> None:
        set_translated_tooltip(
            self.selection_mode_button,
            "Finish selection" if self.selection_mode_button.isChecked() else "Select multiple files",
        )
        set_translated_tooltip(self.bulk_remove_button, "Delete selected files")
        for row in self.asset_rows:
            row.apply_language()
            row.preview_transport.apply_language()

    def _set_selection_mode(self, enabled: bool) -> None:
        self.selection_mode_button.blockSignals(True)
        self.selection_mode_button.setChecked(enabled)
        self.selection_mode_button.set_icon_name("close" if enabled else "list")
        self.selection_mode_button.blockSignals(False)
        set_translated_tooltip(
            self.selection_mode_button,
            "Finish selection" if enabled else "Select multiple files",
        )
        self.selected_count_label.setVisible(enabled)
        self.bulk_remove_button.setVisible(enabled)
        for row in self.asset_rows:
            row.set_selection_mode(enabled)
        self._update_selection_state()

    def _update_selection_state(self, *_args) -> None:
        selected = self.selected_assets()
        set_translated_text(
            self.selected_count_label,
            "{count} selected",
            count=len(selected),
        )
        self.bulk_remove_button.setEnabled(bool(selected))

    def selected_assets(self) -> tuple[SongAsset, ...]:
        return tuple(row.asset for row in self.asset_rows if row.is_selected())

    def _request_bulk_removal(self) -> None:
        selected = self.selected_assets()
        if selected:
            self.remove_assets_requested.emit(selected)

    def _clear_rows(self) -> None:
        self.asset_rows = []
        while self.asset_layout.count():
            item = self.asset_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()


class _SongAssetRow(QFrame):
    open_location_requested = Signal(object)
    remove_requested = Signal(object)
    preview_requested = Signal(object)
    preview_play_toggled = Signal(object)
    preview_seek_requested = Signal(object, int)
    selection_changed = Signal(object, bool)

    def __init__(self, asset: SongAsset) -> None:
        super().__init__()
        self.setObjectName("LibraryAssetRow")
        self.asset = asset
        self._preview_expanded = False
        self._is_previewable = asset.path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS
        self._selection_mode = False
        self._is_hovered = False
        self.setMouseTracking(True)
        self.setProperty("previewExpanded", False)

        self.selection_checkbox = QCheckBox(self)
        self.selection_checkbox.setObjectName("LibraryAssetCheckBox")
        self.selection_checkbox.setFixedWidth(24)
        self.selection_checkbox.setEnabled(asset.can_remove)
        self.selection_checkbox.setVisible(False)
        if not asset.can_remove:
            set_translated_tooltip(
                self.selection_checkbox,
                "This file can only be removed by deleting the entire song.",
            )
        self.selection_checkbox.toggled.connect(
            lambda checked: self.selection_changed.emit(self.asset, checked)
        )

        role_label = QLabel(self)
        set_translated_text(role_label, asset.role)
        role_label.setObjectName("LibraryAssetRole")
        role_label.setFixedWidth(120)

        name_label = QLabel(asset.path.name, self)
        name_label.setObjectName("LibraryAssetName")
        name_label.setToolTip(str(asset.path))
        name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        meta_parts = [part for part in (asset.version_label, _size_label(asset.size_bytes)) if part]
        meta_label = QLabel("  /  ".join(meta_parts), self)
        meta_label.setObjectName("LibraryAssetMeta")
        meta_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(name_label)
        text_layout.addWidget(meta_label)

        ownership_label = QLabel(self)
        set_translated_text(ownership_label, "Managed" if asset.is_managed else "Linked")
        ownership_label.setObjectName("LibraryAssetBadge")
        ownership_label.setProperty("active", False)
        ownership_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ownership_label.setFixedWidth(72)

        active_label = QLabel(self)
        set_translated_text(active_label, "Active")
        active_label.setObjectName("LibraryAssetBadge")
        active_label.setProperty("active", True)
        active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        active_label.setFixedWidth(62)
        active_label.setVisible(asset.is_active)

        self.action_container = QWidget(self)
        self.action_container.setObjectName("LibraryAssetActions")
        self.action_container.setFixedSize(68, 30)

        self.open_button = SvgIconButton("folder", size=30)
        self.open_button.setParent(self.action_container)
        self.open_button.lock_outer_size(30)
        set_translated_tooltip(self.open_button, "Open file location")
        self.open_button.clicked.connect(lambda: self.open_location_requested.emit(asset.path))

        self.remove_button = DangerIconButton(size=30)
        self.remove_button.setParent(self.action_container)
        self.remove_button.setEnabled(asset.can_remove)
        self._apply_remove_tooltip()
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(asset))

        self.remove_slot = QWidget(self.action_container)
        self.remove_slot.setObjectName("LibraryAssetActionSlot")
        self.remove_slot.setFixedSize(30, 30)
        if not asset.can_remove:
            set_translated_tooltip(
                self.remove_slot,
                "This file can only be removed by deleting the entire song.",
            )
        remove_layout = QHBoxLayout(self.remove_slot)
        remove_layout.setContentsMargins(0, 0, 0, 0)
        remove_layout.addWidget(self.remove_button)
        self.remove_button.hide()

        action_layout = QHBoxLayout(self.action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        action_layout.addWidget(self.remove_slot)
        action_layout.addWidget(self.open_button)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        body_layout.addWidget(self.selection_checkbox, 0)
        body_layout.addWidget(role_label, 0)
        body_layout.addLayout(text_layout, 1)
        body_layout.addWidget(ownership_label, 0)
        body_layout.addWidget(active_label, 0)
        body_layout.addWidget(self.action_container, 0)

        self.preview_divider = QFrame()
        self.preview_divider.setObjectName("LibraryPreviewDivider")
        self.preview_divider.setFixedHeight(1)
        self.preview_divider.hide()

        self.preview_transport = TransportControls()
        self.preview_transport.setObjectName("LibraryAssetPreviewTransport")
        self.preview_transport.play_toggled.connect(
            lambda: self.preview_play_toggled.emit(self.asset.path)
        )
        self.preview_transport.seek_requested.connect(
            lambda position_ms: self.preview_seek_requested.emit(self.asset.path, position_ms)
        )
        self.preview_transport.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        layout.addLayout(body_layout)
        layout.addWidget(self.preview_divider)
        layout.addWidget(self.preview_transport)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = True
        self._set_remove_emphasis(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._is_hovered = False
        self._set_remove_emphasis(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selection_mode and self.asset.can_remove:
                self.selection_checkbox.toggle()
            elif not self._selection_mode and self._is_previewable:
                self.preview_requested.emit(self.asset.path)
        super().mouseReleaseEvent(event)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_button.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)
        self.preview_transport.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self._apply_remove_tooltip()
        if not self.asset.can_remove:
            set_translated_tooltip(
                self.remove_slot,
                "This file can only be removed by deleting the entire song.",
            )
            set_translated_tooltip(
                self.selection_checkbox,
                "This file can only be removed by deleting the entire song.",
            )

    def set_selection_mode(self, enabled: bool) -> None:
        self._selection_mode = enabled
        if not enabled:
            self.selection_checkbox.setChecked(False)
        self.selection_checkbox.setVisible(enabled)
        self._sync_remove_visibility()
        self.updateGeometry()

    def is_selected(self) -> bool:
        return self.selection_checkbox.isChecked() and self.asset.can_remove

    def set_preview_expanded(self, is_expanded: bool) -> None:
        expanded = bool(is_expanded and self._is_previewable)
        if self._preview_expanded == expanded:
            return
        self._preview_expanded = expanded
        self.setProperty("previewExpanded", expanded)
        self.preview_divider.setVisible(expanded)
        self.preview_transport.setVisible(expanded)
        if not expanded:
            self.preview_transport.set_playing(False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()

    def set_preview_queue(self, duration_ms: int) -> None:
        self.preview_transport.set_duration(duration_ms)
        self.preview_transport.set_position(0, duration_ms)

    def set_preview_position(self, position_ms: int, duration_ms: int) -> None:
        self.preview_transport.set_position(position_ms, duration_ms)

    def set_preview_playing(self, is_playing: bool) -> None:
        self.preview_transport.set_playing(is_playing)

    def clear_preview(self) -> None:
        self.preview_transport.clear()

    def _set_remove_emphasis(self, emphasized: bool) -> None:
        self._is_hovered = emphasized
        self.remove_button.setProperty("contextHover", self.asset.can_remove and emphasized)
        self._sync_remove_visibility()
        self.remove_button.update()

    def _sync_remove_visibility(self) -> None:
        self.remove_button.setVisible(self._is_hovered and not self._selection_mode)

    def _apply_remove_tooltip(self) -> None:
        tooltip = (
            "Remove Vocal Result"
            if self.asset.can_remove and self.asset.stage == STAGE_VOCAL
            else "Remove"
            if self.asset.can_remove
            else "This file can only be removed by deleting the entire song."
        )
        set_translated_tooltip(self.remove_button, tooltip)


def _source_label(source_type: str) -> str:
    if source_type == "youtube":
        return "YOUTUBE"
    if source_type == "output":
        return "OUTPUT"
    return "LOCAL"


def _size_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return ""


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%y/%m/%d %H:%M")
    except ValueError:
        return ""


def _same_path(first: Path, second: Path) -> bool:
    return first.expanduser().resolve() == second.expanduser().resolve()
