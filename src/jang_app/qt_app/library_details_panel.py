from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text, set_translated_tooltip
from jang_app.qt_app.segmented_stack import SegmentedStack
from jang_app.qt_app.widgets import FeedbackButton, SvgIconButton
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
    open_vocal_requested = Signal(str)
    remove_asset_requested = Signal(str, object)

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
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.source_badge = QLabel("LOCAL")
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedWidth(72)

        self.open_package_button = SvgIconButton("folder", size=34)
        self.open_package_button.setObjectName("ControlIconButton")
        set_translated_tooltip(self.open_package_button, "Open song data location")
        self.open_package_button.clicked.connect(self._open_package_location)

        self.open_vocal_button = FeedbackButton("Open in Vocal")
        self.open_vocal_button.setObjectName("PrimaryButton")
        self.open_vocal_button.setFixedWidth(132)
        self.open_vocal_button.clicked.connect(self._open_in_vocal)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.back_button, 0)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.source_badge, 0)
        header.addWidget(self.open_package_button, 0)
        header.addWidget(self.open_vocal_button, 0)

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
        self.open_vocal_button.setEnabled(details.source_type != "output")
        self.open_package_button.setEnabled(True)

        for stage, page in self.stage_pages.items():
            page.set_assets(details.assets_for(stage), self._theme_mode)

    def clear(self) -> None:
        self._details = None
        set_translated_text(self.title_label, "Song Details")
        self.metadata_label.clear()
        self.open_vocal_button.setEnabled(False)
        self.open_package_button.setEnabled(False)
        for page in self.stage_pages.values():
            page.set_assets((), self._theme_mode)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        self.back_button.set_theme_mode(theme_mode)
        self.open_package_button.set_theme_mode(theme_mode)
        for page in self.stage_pages.values():
            page.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        apply_widget_language(self)
        set_translated_tooltip(self.back_button, "Back to library")
        set_translated_tooltip(self.open_package_button, "Open song data location")

    def _open_package_location(self) -> None:
        if self._details is not None:
            self.open_location_requested.emit(self._details.package_dir)

    def _open_in_vocal(self) -> None:
        if self._details is not None and self._details.source_type != "output":
            self.open_vocal_requested.emit(self._details.song_id)

    def _request_asset_removal(self, asset: SongAsset) -> None:
        if self._details is not None:
            self.remove_asset_requested.emit(self._details.song_id, asset)


class _AssetStagePage(QWidget):
    open_location_requested = Signal(object)
    remove_asset_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._theme_mode = "white"
        self.asset_rows: list[_SongAssetRow] = []

        self.summary_label = QLabel("0 files")
        self.summary_label.setObjectName("LibraryStageSummary")

        self.asset_content = QWidget()
        self.asset_content.setObjectName("LibraryAssetContent")
        self.asset_layout = QVBoxLayout(self.asset_content)
        self.asset_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setObjectName("LibraryAssetScroll")
        scroll.viewport().setObjectName("LibraryAssetViewport")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.asset_content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.summary_label, 0)
        layout.addWidget(scroll, 1)

    def set_assets(self, assets: tuple[SongAsset, ...], theme_mode: str) -> None:
        self._clear_rows()
        self._theme_mode = theme_mode
        set_translated_text(self.summary_label, "{count} files", count=len(assets))
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
            self.asset_rows.append(row)
            self.asset_layout.addWidget(row, 0)
        self.asset_layout.addStretch(1)

    def set_theme_mode(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode
        for row in self.asset_rows:
            row.set_theme_mode(theme_mode)

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

    def __init__(self, asset: SongAsset) -> None:
        super().__init__()
        self.setObjectName("LibraryAssetRow")
        self.asset = asset

        role_label = QLabel()
        set_translated_text(role_label, asset.role)
        role_label.setObjectName("LibraryAssetRole")
        role_label.setFixedWidth(120)

        name_label = QLabel(asset.path.name)
        name_label.setObjectName("LibraryAssetName")
        name_label.setToolTip(str(asset.path))

        meta_parts = [part for part in (asset.version_label, _size_label(asset.size_bytes)) if part]
        meta_label = QLabel("  /  ".join(meta_parts))
        meta_label.setObjectName("LibraryAssetMeta")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(name_label)
        text_layout.addWidget(meta_label)

        ownership_label = QLabel()
        set_translated_text(ownership_label, "Managed" if asset.is_managed else "Linked")
        ownership_label.setObjectName("LibraryAssetBadge")
        ownership_label.setProperty("active", False)
        ownership_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ownership_label.setFixedWidth(72)

        active_label = QLabel()
        set_translated_text(active_label, "Active")
        active_label.setObjectName("LibraryAssetBadge")
        active_label.setProperty("active", True)
        active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        active_label.setFixedWidth(62)
        active_label.setVisible(asset.is_active)

        self.open_button = SvgIconButton("folder", size=30)
        set_translated_tooltip(self.open_button, "Open file location")
        self.open_button.clicked.connect(lambda: self.open_location_requested.emit(asset.path))

        self.remove_button = SvgIconButton("trash", size=30)
        self.remove_button.setObjectName("DangerIconButton")
        set_translated_tooltip(self.remove_button, "Remove")
        self.remove_button.setVisible(asset.can_remove)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(asset))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        layout.addWidget(role_label, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(ownership_label, 0)
        layout.addWidget(active_label, 0)
        layout.addWidget(self.open_button, 0)
        layout.addWidget(self.remove_button, 0)

    def set_theme_mode(self, theme_mode: str) -> None:
        self.open_button.set_theme_mode(theme_mode)
        self.remove_button.set_theme_mode(theme_mode)


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
