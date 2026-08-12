from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.sound_pool_list import SoundPoolList
from jang_app.qt_app.vocal_result_labels import display_compact_result_timestamp
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion


class VocalVersionPool(SoundPoolList):
    """Reusable pool for selecting one stem from saved separation results."""

    selection_changed = Signal(object)

    def __init__(
        self,
        role: str,
        *,
        title_key: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if role not in {"vocal", "instrumental"}:
            raise ValueError(f"Unsupported vocal version pool role: {role}")
        super().__init__(object_name="VocalVersionPool", parent=parent)
        self._role = role
        self._title_key = title_key or ("Vocal Pool" if role == "vocal" else "Instrumental Pool")
        self._empty_key = "No vocal results" if role == "vocal" else "No instrumental results"
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._versions_by_key: dict[str, SongVocalVersion] = {}
        self._selected_key = ""
        self._linked_selection = False
        self.setProperty("stemRole", role)
        self.selected.connect(self._select_card)
        self.apply_language()

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        selected_job_dir: Path | None,
        *,
        preserve_selection: bool = True,
    ) -> SongVocalVersion | None:
        previous_key = self._selected_key
        self._versions = versions
        self._versions_by_key = {_version_key(version): version for version in versions}
        requested_key = _resolved_key(selected_job_dir)
        first_key = next(iter(self._versions_by_key), "")
        self._selected_key = (
            previous_key
            if preserve_selection and previous_key in self._versions_by_key
            else requested_key
            if requested_key in self._versions_by_key
            else first_key
        )
        self._rebuild_cards()
        return self.selected_version()

    def selected_version(self) -> SongVocalVersion | None:
        return self._versions_by_key.get(self._selected_key)

    def select_version(self, job_dir: Path | None) -> bool:
        key = _resolved_key(job_dir)
        if key not in self._versions_by_key:
            return False
        self._selected_key = key
        self.set_selected(key)
        return True

    def set_linked_selection(self, linked: bool) -> None:
        self._linked_selection = bool(linked)
        self.setProperty("linkedSelection", self._linked_selection)
        for card in self.cards.values():
            card.setProperty("linkedSelection", self._linked_selection)
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def apply_language(self) -> None:
        self.set_copy(tr(self._title_key), tr(self._empty_key))
        self._rebuild_cards()

    def _rebuild_cards(self) -> None:
        cards = tuple(self._build_card(version) for version in self._versions)
        self.set_cards(cards, self._selected_key)

    def _build_card(self, version: SongVocalVersion) -> SoundPoolItemCard:
        path = version.vocals_path if self._role == "vocal" else version.instrumental_path
        card = SoundPoolItemCard(
            _version_key(version),
            role="original_vocal" if self._role == "vocal" else "instrumental",
            path=path,
            title=tr(version.separation_recipe_label or version.label),
            badge=tr("Vocal") if self._role == "vocal" else tr("Inst."),
            detail=display_compact_result_timestamp(version.added_at),
            object_name="VocalVersionCard",
        )
        card.set_list_mode(True)
        card.set_theme_mode(self._theme_mode)
        card.setProperty("linkedSelection", self._linked_selection)
        summary = version.separation_recipe_summary.strip()
        card.setToolTip(f"{summary}\n{path}" if summary else str(path))
        return card

    def _select_card(self, key: str) -> None:
        if key not in self._versions_by_key:
            return
        if key == self._selected_key:
            self.set_selected(key)
            return
        self._selected_key = key
        self.set_selected(key)
        self.selection_changed.emit(self._versions_by_key[key])


def _version_key(version: SongVocalVersion) -> str:
    return _resolved_key(version.job_dir)


def _resolved_key(path: Path | None) -> str:
    if path is None:
        return ""
    return str(path.expanduser().resolve())
