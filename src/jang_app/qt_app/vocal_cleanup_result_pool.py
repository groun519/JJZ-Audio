from __future__ import annotations

from PySide6.QtCore import Signal

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.sound_pool_list import SoundPoolList
from jang_app.qt_app.widgets import DangerIconButton
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.i18n import tr
from jang_app.services.vocal_cleanup import VocalCleanupResult


class VocalCleanupResultPool(SoundPoolList):
    result_changed = Signal(object)
    remove_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__(object_name="VocalCleanupResultPool")
        self._results: tuple[VocalCleanupResult, ...] = ()
        self._results_by_id: dict[str, VocalCleanupResult] = {}
        self._selected_id = ""
        self.selected.connect(self._select_result)
        self.apply_language()

    def set_results(
        self,
        results: tuple[VocalCleanupResult, ...],
        selected_id: str = "",
    ) -> VocalCleanupResult | None:
        self._results = tuple(result for result in results if result.path.is_file())
        self._results_by_id = {result.result_id: result for result in self._results}
        self._selected_id = (
            selected_id
            if selected_id in self._results_by_id
            else self._selected_id
            if self._selected_id in self._results_by_id
            else self._results[0].result_id
            if self._results
            else ""
        )
        self._rebuild()
        return self.selected_result()

    def selected_result(self) -> VocalCleanupResult | None:
        return self._results_by_id.get(self._selected_id)

    def apply_language(self) -> None:
        self.set_copy(tr("Cleaned Vocals"), tr("No cleaned vocals yet"))
        self._rebuild()

    def _rebuild(self) -> None:
        cards = tuple(self._build_card(result) for result in self._results)
        self.set_cards(cards, self._selected_id)

    def _build_card(self, result: VocalCleanupResult) -> SoundPoolItemCard:
        try:
            duration_ms = read_audio_metadata(result.path).duration_ms
        except Exception:
            duration_ms = None
        card = SoundPoolItemCard(
            result.result_id,
            role="original_vocal",
            path=result.path,
            title=_result_label(result),
            badge=tr("Clean"),
            detail=result.path.name,
            duration_ms=duration_ms,
            object_name="VocalVersionCard",
        )
        card.set_list_mode(True)
        card.set_theme_mode(self._theme_mode)
        remove_button = DangerIconButton(size=28)
        remove_button.setToolTip(tr("Delete cleaned vocal"))
        remove_button.clicked.connect(
            lambda _checked=False, value=result: self.remove_requested.emit(value)
        )
        card.set_action_widget(remove_button)
        return card

    def _select_result(self, result_id: str) -> None:
        result = self._results_by_id.get(result_id)
        if result is None:
            return
        self._selected_id = result_id
        self.set_selected(result_id)
        self.result_changed.emit(result)


def _result_label(result: VocalCleanupResult) -> str:
    prefix = "Clean vocal "
    if result.label.startswith(prefix):
        return tr("Clean vocal {number}").format(number=result.label[len(prefix) :])
    return result.label
