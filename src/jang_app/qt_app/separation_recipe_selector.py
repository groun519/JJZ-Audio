from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.qt_app.widgets import FeedbackButton
from jang_app.services.i18n import tr
from jang_app.services.separation_assets import (
    SeparationAssetStatus,
    combine_separation_asset_status,
    format_byte_size,
    separation_asset_status,
)
from jang_app.services.separation_recipe import (
    HIGH_QUALITY_RECIPE,
    SEPARATION_RECIPES,
    SeparationRecipe,
)


AssetStatusResolver = Callable[[str], SeparationAssetStatus]

_DESCRIPTION_BY_RECIPE_ID = {
    "demucs-standard-v1": "Balanced separation for everyday work and quick comparisons.",
    "demucs-high-quality-v1": (
        "Repeats the analysis twice and corrects both stems back to the original mix."
    ),
    "demucs-maximum-v1": (
        "Combines htdemucs_ft and htdemucs after four shifted analyses per model. "
        "This method takes the longest."
    ),
}


class SeparationRecipeSelector(QWidget):
    recipe_changed = Signal(object)

    def __init__(
        self,
        recipes: Iterable[SeparationRecipe] = SEPARATION_RECIPES,
        *,
        selected_recipe_id: str = HIGH_QUALITY_RECIPE.recipe_id,
        asset_status_resolver: AssetStatusResolver = separation_asset_status,
    ) -> None:
        super().__init__()
        self.setObjectName("SeparationRecipeSelector")
        self._recipes = tuple(recipes)
        if not self._recipes:
            raise ValueError("SeparationRecipeSelector requires at least one recipe")
        self._recipes_by_id = {recipe.recipe_id: recipe for recipe in self._recipes}
        self._asset_status_resolver = asset_status_resolver
        self._selected_recipe = self._recipes_by_id.get(
            selected_recipe_id,
            self._recipes[0],
        )

        method_label = QLabel()
        method_label.setObjectName("FieldLabel")
        set_translated_text(method_label, "Separation method")

        control = QFrame()
        control.setObjectName("SegmentedControl")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.buttons: dict[str, FeedbackButton] = {}
        for recipe in self._recipes:
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setProperty("recipeId", recipe.recipe_id)
            set_translated_text(button, recipe.label)
            button.clicked.connect(
                lambda _checked=False, recipe_id=recipe.recipe_id: self.select_recipe(
                    recipe_id,
                    emit=True,
                )
            )
            self.button_group.addButton(button)
            self.buttons[recipe.recipe_id] = button
            control_layout.addWidget(button, 1)

        details = QFrame()
        details.setObjectName("InsetCard")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 13, 14, 13)
        details_layout.setSpacing(9)

        details_header = QHBoxLayout()
        details_header.setContentsMargins(0, 0, 0, 0)
        details_header.setSpacing(8)
        self.detail_title = QLabel()
        self.detail_title.setObjectName("CardTitle")
        self.asset_status_label = QLabel()
        self.asset_status_label.setObjectName("SeparationAssetStatus")
        details_header.addWidget(self.detail_title, 1)
        details_header.addWidget(self.asset_status_label, 0)

        self.detail_description = QLabel()
        self.detail_description.setObjectName("MutedText")
        self.detail_description.setWordWrap(True)
        self.detail_description.setMinimumHeight(
            self.detail_description.fontMetrics().lineSpacing() * 2 + 2
        )

        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 2, 0, 0)
        detail_grid.setHorizontalSpacing(16)
        detail_grid.setVerticalSpacing(7)
        self.model_value = _detail_row(detail_grid, 0, "Model")
        self.passes_value = _detail_row(detail_grid, 1, "Analysis passes")
        self.overlap_value = _detail_row(detail_grid, 2, "Overlap")
        self.precision_value = _detail_row(detail_grid, 3, "Output precision")
        self.consistency_value = _detail_row(detail_grid, 4, "Mix correction")
        detail_grid.setColumnStretch(1, 1)

        details_layout.addLayout(details_header)
        details_layout.addWidget(self.detail_description)
        details_layout.addLayout(detail_grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(method_label)
        layout.addWidget(control)
        layout.addWidget(details)

        self.select_recipe(self._selected_recipe.recipe_id)

    def selected_recipe(self) -> SeparationRecipe:
        return self._selected_recipe

    def select_recipe(self, recipe_id: str, *, emit: bool = False) -> None:
        recipe = self._recipes_by_id.get(recipe_id)
        if recipe is None:
            return
        changed = recipe.recipe_id != self._selected_recipe.recipe_id
        self._selected_recipe = recipe
        self.buttons[recipe.recipe_id].setChecked(True)
        self._refresh_details()
        if emit and changed:
            self.recipe_changed.emit(recipe)

    def refresh_asset_status(self) -> None:
        self._refresh_details()

    def apply_language(self) -> None:
        apply_widget_language(self)
        self._refresh_details()

    def _refresh_details(self) -> None:
        recipe = self._selected_recipe
        status = combine_separation_asset_status(
            self._asset_status_resolver(model) for model in recipe.models
        )
        self.detail_title.setText(tr(recipe.label))
        self.detail_description.setText(
            tr(
                _DESCRIPTION_BY_RECIPE_ID.get(
                    recipe.recipe_id,
                    "Custom separation settings.",
                )
            )
        )
        self.model_value.setText(" + ".join(recipe.models))
        if recipe.is_ensemble:
            self.passes_value.setText(
                tr(
                    "{models} models x {count} shifts",
                    models=len(recipe.models),
                    count=recipe.shifts,
                )
            )
        else:
            self.passes_value.setText(tr("{count} passes", count=recipe.shifts))
        self.overlap_value.setText(f"{round(recipe.overlap * 100):d}%")
        self.precision_value.setText("32-bit float" if recipe.float32 else "16-bit")
        self.consistency_value.setText(
            tr("Applied") if recipe.mixture_consistency else tr("Not applied")
        )
        if status.ready:
            availability = "ready"
            status_text = tr("Model ready")
        else:
            availability = "download"
            status_text = tr(
                "First use downloads about {size}",
                size=format_byte_size(status.missing_bytes),
            )
        self.asset_status_label.setText(status_text)
        self.asset_status_label.setProperty("availability", availability)
        self.asset_status_label.style().unpolish(self.asset_status_label)
        self.asset_status_label.style().polish(self.asset_status_label)


def _detail_row(layout: QGridLayout, row: int, label: str) -> QLabel:
    name = QLabel()
    name.setObjectName("SeparationRecipeField")
    set_translated_text(name, label)
    value = QLabel()
    value.setObjectName("SeparationRecipeValue")
    layout.addWidget(name, row, 0)
    layout.addWidget(value, row, 1)
    return value
