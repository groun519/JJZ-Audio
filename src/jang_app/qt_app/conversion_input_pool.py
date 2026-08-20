from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.sound_pool_list import SoundPoolList
from jang_app.qt_app.vocal_result_labels import display_compact_result_timestamp
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_input import VocalInputChoice


class ConversionInputPool(SoundPoolList):
    choice_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__(object_name="VocalVersionPool")
        self.setProperty("poolContext", "conversionInput")
        self._choices: tuple[VocalInputChoice, ...] = ()
        self._choices_by_id: dict[str, VocalInputChoice] = {}
        self._selected_id = ""
        self.selected.connect(self._select_card)
        self.apply_language()

    def set_choices(
        self,
        choices: tuple[VocalInputChoice, ...],
        *,
        selected_job_dir: Path | None = None,
        preferred_path: Path | None = None,
        preserve_selection: bool = True,
    ) -> VocalInputChoice | None:
        previous = self._selected_id
        self._choices = choices
        self._choices_by_id = {choice.choice_id: choice for choice in choices}
        preferred_resolved = preferred_path.expanduser().resolve() if preferred_path is not None else None
        preferred_id = next(
            (
                choice.choice_id
                for choice in choices
                if preferred_resolved is not None
                and choice.path.expanduser().resolve() == preferred_resolved
            ),
            "",
        )
        selected_root = selected_job_dir.expanduser().resolve() if selected_job_dir is not None else None
        owner_id = next(
            (
                choice.choice_id
                for choice in choices
                if choice.kind == "original"
                and selected_root is not None
                and choice.version.job_dir.expanduser().resolve() == selected_root
            ),
            "",
        )
        self._selected_id = (
            previous
            if preserve_selection and previous in self._choices_by_id
            else preferred_id
            if preferred_id in self._choices_by_id
            else owner_id
            if owner_id in self._choices_by_id
            else choices[0].choice_id
            if choices
            else ""
        )
        self._rebuild()
        return self.selected_choice()

    def selected_choice(self) -> VocalInputChoice | None:
        return self._choices_by_id.get(self._selected_id)

    def selected_version(self) -> SongVocalVersion | None:
        choice = self.selected_choice()
        return choice.version if choice is not None else None

    def selected_path(self) -> Path | None:
        choice = self.selected_choice()
        return choice.path if choice is not None else None

    def select_path(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        choice = next(
            (item for item in self._choices if item.path.expanduser().resolve() == resolved),
            None,
        )
        if choice is None:
            return False
        self._selected_id = choice.choice_id
        self.set_selected(self._selected_id)
        return True

    def apply_language(self) -> None:
        self.set_copy(tr("Conversion Input"), tr("No vocal results"))
        self._rebuild()

    def _rebuild(self) -> None:
        cards = tuple(self._build_card(choice) for choice in self._choices)
        self.set_cards(cards, self._selected_id)

    def _build_card(self, choice: VocalInputChoice) -> SoundPoolItemCard:
        split = choice.split_stem is not None
        detail = (
            tr(choice.version.separation_recipe_label or choice.version.label)
            if split
            else display_compact_result_timestamp(choice.version.added_at)
        )
        card = SoundPoolItemCard(
            choice.choice_id,
            role="original_vocal",
            path=choice.path,
            title=tr(choice.label),
            badge=tr(_choice_badge(choice.kind)),
            detail=detail,
            object_name="VocalVersionCard",
        )
        card.set_list_mode(True)
        card.set_theme_mode(self._theme_mode)
        card.setToolTip(str(choice.path))
        return card

    def _select_card(self, choice_id: str) -> None:
        choice = self._choices_by_id.get(choice_id)
        if choice is None:
            return
        if choice_id == self._selected_id:
            self.set_selected(choice_id)
            return
        self._selected_id = choice_id
        self.set_selected(choice_id)
        self.choice_changed.emit(choice)


def _choice_badge(kind: str) -> str:
    return {
        "lead": "Lead",
        "backing": "Backing",
        "cleanup": "Clean",
    }.get(kind, "Vocal")
