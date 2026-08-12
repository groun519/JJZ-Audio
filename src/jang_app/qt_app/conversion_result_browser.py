from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.sound_pool_list import SoundPoolList
from jang_app.qt_app.vocal_result_labels import (
    vocal_take_label,
    vocal_take_summary,
    vocal_take_tooltip,
)
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalProject


class ConversionResultBrowser(SoundPoolList):
    """Selects one converted vocal take from every result of the work song."""

    converted_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__(object_name="ConversionVocalPool")
        self.setMinimumWidth(260)
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._projects_by_job: dict[Path, VocalProject] = {}
        self._owners_by_path: dict[Path, SongVocalVersion] = {}
        self._selected_converted_path: Path | None = None
        self.title_label.setObjectName("ConversionPoolTitle")

        self.selected.connect(self._select_converted)
        self.apply_language()
        self.set_versions(())

    @property
    def cards(self) -> dict[Path, SoundPoolItemCard]:
        return {
            _resolved(Path(key)): card
            for key, card in super().cards.items()
        }

    def set_result(
        self,
        result: SongVocalVersion | None,
        project: VocalProject | None = None,
    ) -> None:
        projects = {result.job_dir: project} if result is not None and project is not None else {}
        self.set_versions((result,) if result is not None else (), projects=projects)

    def set_versions(
        self,
        versions: tuple[SongVocalVersion, ...],
        *,
        projects: dict[Path, VocalProject] | None = None,
        preferred_path: Path | None = None,
    ) -> None:
        previous = self._selected_converted_path
        self._versions = versions
        self._projects_by_job = {
            _resolved(job_dir): project
            for job_dir, project in (projects or {}).items()
        }
        self._owners_by_path = {
            _resolved(path): version
            for version in versions
            for path in version.converted_vocal_paths
        }
        paths = self.converted_paths()
        valid_paths = {_resolved(path) for path in paths}
        requested = _resolved(preferred_path) if preferred_path is not None else None
        active = next(
            (
                _resolved(version.active_converted_path)
                for version in versions
                if version.active_converted_path is not None
                and _resolved(version.active_converted_path) in valid_paths
            ),
            None,
        )
        self._selected_converted_path = (
            requested
            if requested in valid_paths
            else previous
            if previous in valid_paths
            else active
            if active is not None
            else _resolved(paths[0])
            if paths
            else None
        )
        self._rebuild_cards()

    def converted_paths(self) -> tuple[Path, ...]:
        return tuple(self._owners_by_path)

    def projects(self) -> tuple[VocalProject, ...]:
        return tuple(self._projects_by_job.values())

    def version_for_path(self, path: Path | None) -> SongVocalVersion | None:
        return self._owners_by_path.get(_resolved(path)) if path is not None else None

    def selected_path(self) -> Path | None:
        return self._selected_converted_path

    def select_converted(self, path: Path | None) -> bool:
        if path is None:
            self._selected_converted_path = None
            self.set_selected("")
            return False
        resolved = _resolved(path)
        if str(resolved) not in super().cards:
            return False
        self._selected_converted_path = resolved
        self.set_selected(str(resolved))
        return True

    def apply_language(self) -> None:
        self.set_copy(tr("RVC Pool"), tr("No converted vocal"))
        self._rebuild_cards()

    def _rebuild_cards(self) -> None:
        paths = self.converted_paths()
        takes_by_path = {
            _resolved(take.output_path): take
            for project in self._projects_by_job.values()
            for take in project.takes
        }
        cards: list[SoundPoolItemCard] = []
        for path in paths:
            resolved = _resolved(path)
            take = takes_by_path.get(resolved)
            detail = vocal_take_summary(take)
            version = self._owners_by_path.get(resolved)
            source_label = (
                tr(version.separation_recipe_label or version.label)
                if version is not None
                else ""
            )
            if source_label:
                detail = f"{source_label}  /  {detail}"
            card = SoundPoolItemCard(
                str(resolved),
                role="converted_vocal",
                path=path,
                title=vocal_take_label(take, path),
                badge=tr("RVC"),
                detail=detail,
                object_name="ConversionVocalCard",
            )
            card.set_list_mode(True)
            card.set_theme_mode(self._theme_mode)
            card.setToolTip(vocal_take_tooltip(take, path))
            cards.append(card)
        selected_key = str(self._selected_converted_path) if self._selected_converted_path else ""
        self.set_cards(tuple(cards), selected_key)

    def _select_converted(self, card_id: str) -> None:
        selected = _resolved(Path(card_id))
        if selected == self._selected_converted_path:
            self.set_selected(card_id)
            return
        self._selected_converted_path = selected
        self.set_selected(card_id)
        self.converted_selected.emit(selected)


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()
