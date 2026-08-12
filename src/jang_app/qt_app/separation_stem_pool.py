from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jang_app.qt_app.sound_pool_theme import apply_sound_pool_theme, pair_button_palette
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.qt_app.widgets import SvgIconButton
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion


class SeparationStemPoolPanel(QFrame):
    """Selects the vocal and instrumental stems used by separation preview."""

    selection_changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SeparationStemPoolPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(260)
        self._versions_by_key: dict[str, SongVocalVersion] = {}
        self._selected_vocal_key = ""
        self._selected_instrumental_key = ""
        self._last_selected_role = "vocal"

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.pair_status_label = QLabel()
        self.pair_status_label.setObjectName("SeparationPairStatus")
        self.pair_button = _PairLinkButton()
        self.pair_button.setObjectName("SeparationPairButton")
        self.pair_button.setCheckable(True)
        self.pair_button.setChecked(True)
        self.pair_button.clicked.connect(self._on_pair_mode_changed)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(7)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.pair_status_label)
        header.addWidget(self.pair_button)

        self.vocal_pool = VocalVersionPool("vocal")
        self.instrumental_pool = VocalVersionPool("instrumental")
        self.vocal_pool.set_linked_selection(True)
        self.instrumental_pool.set_linked_selection(True)
        self.vocal_pool.selection_changed.connect(
            lambda version: self._select_stem("vocal", version)
        )
        self.instrumental_pool.selection_changed.connect(
            lambda version: self._select_stem("instrumental", version)
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.vocal_pool, 1)
        layout.addWidget(self.instrumental_pool, 1)
        apply_sound_pool_theme(self, "white")
        self.apply_language()

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
    ) -> tuple[SongVocalVersion | None, SongVocalVersion | None]:
        previous_vocal = self._selected_vocal_key
        previous_instrumental = self._selected_instrumental_key
        self._versions_by_key = {_version_key(version): version for version in versions}
        requested_key = _resolved_key(selected_job_dir)
        first_key = next(iter(self._versions_by_key), "")
        preferred_key = (
            requested_key
            if requested_key in self._versions_by_key
            else previous_vocal
            if previous_vocal in self._versions_by_key
            else first_key
        )
        self._selected_vocal_key = preferred_key
        self._selected_instrumental_key = (
            preferred_key
            if self.pair_button.isChecked()
            else previous_instrumental
            if previous_instrumental in self._versions_by_key
            else preferred_key
        )
        self.vocal_pool.set_versions(
            versions,
            _job_dir(self._versions_by_key, self._selected_vocal_key),
            preserve_selection=False,
        )
        self.instrumental_pool.set_versions(
            versions,
            _job_dir(self._versions_by_key, self._selected_instrumental_key),
            preserve_selection=False,
        )
        return self.selected_versions()

    def selected_versions(
        self,
    ) -> tuple[SongVocalVersion | None, SongVocalVersion | None]:
        return (
            self._versions_by_key.get(self._selected_vocal_key),
            self._versions_by_key.get(self._selected_instrumental_key),
        )

    def is_paired(self) -> bool:
        return self.pair_button.isChecked()

    def set_paired(self, paired: bool) -> None:
        if self.pair_button.isChecked() == paired:
            return
        self.pair_button.setChecked(paired)
        self._on_pair_mode_changed(paired)

    def set_theme_mode(self, theme_mode: str) -> None:
        apply_sound_pool_theme(self, theme_mode)
        self.pair_button.set_theme_mode(theme_mode)
        self.vocal_pool.set_theme_mode(theme_mode)
        self.instrumental_pool.set_theme_mode(theme_mode)

    def apply_language(self) -> None:
        self.title_label.setText(tr("Stem Pool"))
        self.vocal_pool.apply_language()
        self.instrumental_pool.apply_language()
        self._update_pair_copy()

    def _select_stem(self, role: str, version: SongVocalVersion) -> None:
        key = _version_key(version)
        if key not in self._versions_by_key:
            return
        self._last_selected_role = role
        if role == "vocal":
            self._selected_vocal_key = key
        else:
            self._selected_instrumental_key = key
        if self.pair_button.isChecked():
            self._selected_vocal_key = key
            self._selected_instrumental_key = key
        self._sync_card_selection()
        self.selection_changed.emit(*self.selected_versions())

    def _on_pair_mode_changed(self, paired: bool = False) -> None:
        if paired:
            key = (
                self._selected_vocal_key
                if self._last_selected_role == "vocal"
                else self._selected_instrumental_key
            )
            if key in self._versions_by_key:
                self._selected_vocal_key = key
                self._selected_instrumental_key = key
        self._update_pair_copy()
        self._sync_card_selection()
        self.selection_changed.emit(*self.selected_versions())

    def _update_pair_copy(self) -> None:
        paired = self.pair_button.isChecked()
        self.vocal_pool.set_linked_selection(paired)
        self.instrumental_pool.set_linked_selection(paired)
        self.pair_status_label.setProperty("paired", paired)
        self.pair_status_label.setText(tr("Paired") if paired else tr("Independent"))
        self.pair_button.setToolTip(
            tr("Keep vocal and instrumental from the same separation result")
            if paired
            else tr("Select vocal and instrumental independently")
        )
        self.pair_status_label.style().unpolish(self.pair_status_label)
        self.pair_status_label.style().polish(self.pair_status_label)
        self.pair_status_label.update()
        self.pair_button.update()

    def _sync_card_selection(self) -> None:
        self.vocal_pool.select_version(
            _job_dir(self._versions_by_key, self._selected_vocal_key)
        )
        self.instrumental_pool.select_version(
            _job_dir(self._versions_by_key, self._selected_instrumental_key)
        )


class _PairLinkButton(SvgIconButton):
    def __init__(self) -> None:
        super().__init__("link", size=32)

    def _button_palette(self) -> dict[str, QColor]:
        return pair_button_palette(
            self._theme_mode,
            checked=self.isChecked(),
            enabled=self.isEnabled(),
            hovered=self._is_pointer_hovered(),
            pressed=self._is_pointer_pressed() or self.isDown(),
        )


def _version_key(version: SongVocalVersion) -> str:
    return _resolved_key(version.job_dir)


def _resolved_key(path: Path | None) -> str:
    if path is None:
        return ""
    return str(path.expanduser().resolve())


def _job_dir(
    versions_by_key: dict[str, SongVocalVersion],
    key: str,
) -> Path | None:
    version = versions_by_key.get(key)
    return version.job_dir if version is not None else None
