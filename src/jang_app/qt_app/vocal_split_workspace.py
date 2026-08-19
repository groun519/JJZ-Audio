from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.result_transport_bar import ResultTransportBar
from jang_app.qt_app.vocal_split_group_list import VocalSplitGroupList
from jang_app.qt_app.vocal_split_timeline import VocalSplitTimelinePanel
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.qt_app.workspace_splitter import create_workspace_splitter
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_split import (
    VocalReferenceRegion,
    VocalSplitRun,
    VocalSplitStem,
)


class VocalSplitWorkspace(QWidget):
    source_changed = Signal(object)
    create_group_requested = Signal(object)
    group_selected = Signal(object)
    stem_selected = Signal(object, object)
    rename_requested = Signal(object, object)
    remove_run_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocalSplitWorkspace")
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._selected_source_key = ""
        self._selected_group_by_source: dict[str, str] = {}

        self.method_panel = QFrame()
        self.method_panel.setObjectName("Panel")
        self.method_panel.setMinimumWidth(320)
        method_layout = QVBoxLayout(self.method_panel)
        method_layout.setContentsMargins(20, 20, 20, 20)
        method_layout.setSpacing(14)
        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.source_selector = VocalVersionPool(
            "vocal",
            title_key="Vocal to separate",
        )
        self.source_selector.setMinimumHeight(180)
        self.source_selector.setMaximumHeight(280)
        self.source_selector.selection_changed.connect(self._on_source_changed)

        self.group_create_card = QFrame()
        self.group_create_card.setObjectName("InsetCard")
        group_create_layout = QVBoxLayout(self.group_create_card)
        group_create_layout.setContentsMargins(14, 13, 14, 13)
        group_create_layout.setSpacing(9)
        self.group_create_title = QLabel()
        self.group_create_title.setObjectName("CardTitle")
        self.group_create_description = QLabel()
        self.group_create_description.setObjectName("MutedText")
        self.group_create_description.setWordWrap(True)
        self.create_group_button = FeedbackButton()
        self.create_group_button.setObjectName("PrimaryButton")
        self.create_group_button.clicked.connect(self._request_group_creation)
        group_create_layout.addWidget(self.group_create_title)
        group_create_layout.addWidget(self.group_create_description)
        group_create_layout.addWidget(self.create_group_button)

        method_layout.addWidget(self.title_label)
        method_layout.addWidget(self.source_selector)
        method_layout.addWidget(self.group_create_card)
        method_layout.addStretch(1)

        self.group_list = VocalSplitGroupList()
        self.group_list.group_selected.connect(self._on_group_selected)
        self.group_list.remove_requested.connect(self.remove_run_requested.emit)
        self.result_timeline = VocalSplitTimelinePanel()
        self.result_timeline.stem_selected.connect(self._on_stem_selected)
        self.result_timeline.rename_requested.connect(self.rename_requested.emit)
        # MainWindow keeps one task-progress target while the widget now lives
        # in the selected-vocal tool on the right.
        self.action = self.result_timeline.action

        self.splitter = create_workspace_splitter(
            (self.method_panel, self.group_list, self.result_timeline),
            object_name="VocalSplitWorkspaceSplitter",
            sizes=(370, 310, 820),
            stretch_factors=(0, 0, 1),
            collapsible=(True, True, False),
        )
        self.transport_bar = ResultTransportBar()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.transport_bar, 0)
        self.apply_language()

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
    ) -> SongVocalVersion | None:
        self._versions = versions
        selected = self.source_selector.set_versions(versions, selected_job_dir)
        selected_source_key = _source_key(selected)
        if selected_source_key != self._selected_source_key:
            self._selected_source_key = selected_source_key
            self.group_list.set_groups(())
            self.result_timeline.set_group(None)
        self.create_group_button.setEnabled(selected is not None)
        return selected

    def selected_version(self) -> SongVocalVersion | None:
        return self.source_selector.selected_version()

    def set_groups(
        self,
        groups: tuple[VocalSplitRun, ...],
        preferred_path: Path | None = None,
        preferred_group_id: str = "",
    ) -> VocalSplitStem | None:
        source_key = _source_key(self.selected_version())
        preferred_group = _group_containing_path(groups, preferred_path)
        selected_group_id = (
            preferred_group_id
            if preferred_group_id
            else preferred_group.run_id
            if preferred_group is not None
            else self._selected_group_by_source.get(source_key, "")
        )
        selected_group = self.group_list.set_groups(groups, selected_group_id)
        if selected_group is not None and source_key:
            self._selected_group_by_source[source_key] = selected_group.run_id
        return self.result_timeline.set_group(selected_group, preferred_path)

    def selected_group(self) -> VocalSplitRun | None:
        return self.group_list.selected_group()

    def selected_stem(self) -> VocalSplitStem | None:
        return self.result_timeline.selected_stem()

    def reference_regions(self) -> tuple[VocalReferenceRegion, ...]:
        return self.result_timeline.reference_regions()

    def set_backend_status(
        self,
        available: bool,
        detail: str,
        *,
        minimum_reference_ms: int = 1_000,
        maximum_reference_ms: int = 60_000,
    ) -> None:
        self.result_timeline.set_backend_status(
            available,
            detail,
            minimum_reference_ms=minimum_reference_ms,
            maximum_reference_ms=maximum_reference_ms,
        )

    def refresh_asset_status(self) -> None:
        self.result_timeline.refresh_backend_status()

    def set_theme_mode(self, theme_mode: str) -> None:
        self.source_selector.set_theme_mode(theme_mode)
        self.group_list.set_theme_mode(theme_mode)
        self.result_timeline.set_theme_mode(theme_mode)
        self.transport_bar.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Vocal Separation"))
        self.group_create_title.setText(tr("Create vocal group"))
        self.group_create_description.setText(
            tr("Creates a group with the selected vocal. No audio processing starts yet.")
        )
        self.create_group_button.setText(tr("Create Group"))
        self.source_selector.apply_language()
        self.group_list.apply_language()
        self.result_timeline.apply_language()
        self.transport_bar.apply_language()

    def _request_group_creation(self) -> None:
        version = self.selected_version()
        if version is not None:
            self.create_group_requested.emit(version)

    def _on_source_changed(self, version: SongVocalVersion) -> None:
        self._selected_source_key = _source_key(version)
        self.group_list.set_groups(())
        self.result_timeline.set_group(None)
        self.create_group_button.setEnabled(True)
        self.source_changed.emit(version)

    def _on_group_selected(self, group: VocalSplitRun) -> None:
        source_key = _source_key(self.selected_version())
        if source_key:
            self._selected_group_by_source[source_key] = group.run_id
        self.result_timeline.set_group(group)
        self.group_selected.emit(group)

    def _on_stem_selected(
        self,
        group: VocalSplitRun,
        stem: VocalSplitStem,
    ) -> None:
        self.stem_selected.emit(group, stem)


def _source_key(version: SongVocalVersion | None) -> str:
    if version is None:
        return ""
    return str(version.job_dir.expanduser().resolve())


def _group_containing_path(
    groups: tuple[VocalSplitRun, ...],
    path: Path | None,
) -> VocalSplitRun | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    return next(
        (
            group
            for group in groups
            if any(stem.path.expanduser().resolve() == resolved for stem in group.stems)
        ),
        None,
    )
