from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
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
    CUSTOM_COMPONENT_RECIPES,
    CUSTOM_RECIPE,
    FAST_RECIPE,
    PRECISION_RECIPE,
    SEPARATION_RECIPES,
    VOCAL_MELBAND_RECIPE,
    SeparationRecipe,
    custom_component_label,
    custom_separation_recipe,
)


AssetStatusResolver = Callable[[str], SeparationAssetStatus]

_DESCRIPTION_BY_RECIPE_ID = {
    FAST_RECIPE.recipe_id: (
        "Uses HTDemucs for both stems. It is the quickest option and works well for previews, "
        "lower-spec systems, and songs where ambience is part of the vocal sound."
    ),
    VOCAL_MELBAND_RECIPE.recipe_id: (
        "Uses Vocal MelBand-RoFormer for both stems. It takes longer, but usually captures more "
        "of the vocal line and is the recommended preset before RVC conversion."
    ),
    CUSTOM_RECIPE.recipe_id: (
        "Choose the vocal and instrumental models independently. Selecting the same model runs "
        "it once; selecting different models runs both and combines the chosen stems."
    ),
}

_USE_CASE_BY_RECIPE_ID = {
    FAST_RECIPE.recipe_id: "Preview, ambience-heavy songs, and low-spec systems",
    VOCAL_MELBAND_RECIPE.recipe_id: "RVC conversion and final vocal production",
    CUSTOM_RECIPE.recipe_id: "Songs that need different vocal and instrumental models",
}


class SeparationRecipeSelector(QWidget):
    recipe_changed = Signal(object)

    def __init__(
        self,
        recipes: Iterable[SeparationRecipe] = SEPARATION_RECIPES,
        *,
        custom_model_recipes: Iterable[SeparationRecipe] = CUSTOM_COMPONENT_RECIPES,
        selected_recipe_id: str = VOCAL_MELBAND_RECIPE.recipe_id,
        asset_status_resolver: AssetStatusResolver = separation_asset_status,
    ) -> None:
        super().__init__()
        self.setObjectName("SeparationRecipeSelector")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._recipes = tuple(recipes)
        self._custom_model_recipes = tuple(custom_model_recipes)
        if not self._recipes:
            raise ValueError("SeparationRecipeSelector requires at least one recipe")
        if not self._custom_model_recipes:
            raise ValueError("Custom separation requires at least one component model")
        self._recipes_by_id = {recipe.recipe_id: recipe for recipe in self._recipes}
        self._custom_models_by_id = {
            recipe.recipe_id: recipe for recipe in self._custom_model_recipes
        }
        self._asset_status_resolver = asset_status_resolver
        self._custom_vocal_recipe_id = CUSTOM_RECIPE.vocal_recipe_id
        self._custom_instrumental_recipe_id = CUSTOM_RECIPE.instrumental_recipe_id
        if selected_recipe_id == PRECISION_RECIPE.recipe_id:
            selected_recipe_id = VOCAL_MELBAND_RECIPE.recipe_id
        self._selected_recipe = self._recipes_by_id.get(
            selected_recipe_id,
            self._recipes[0],
        )

        self.method_control = QFrame()
        self.method_control.setObjectName("SegmentedControl")
        self.method_control.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        method_layout = QHBoxLayout(self.method_control)
        method_layout.setContentsMargins(4, 4, 4, 4)
        method_layout.setSpacing(4)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.buttons: dict[str, FeedbackButton] = {}
        for recipe in self._recipes:
            button = FeedbackButton()
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            set_translated_text(
                button,
                "Custom" if recipe.recipe_id == CUSTOM_RECIPE.recipe_id else recipe.label,
            )
            button.clicked.connect(
                lambda _checked=False, recipe_id=recipe.recipe_id: self.select_recipe(
                    recipe_id,
                    emit=True,
                )
            )
            self.button_group.addButton(button)
            self.buttons[recipe.recipe_id] = button
            method_layout.addWidget(button, 1)

        details = QFrame()
        details.setObjectName("InsetCard")
        details.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 13, 14, 13)
        details_layout.setSpacing(9)

        details_header = QHBoxLayout()
        details_header.setContentsMargins(0, 0, 0, 0)
        details_header.setSpacing(8)
        self.detail_title = QLabel()
        self.detail_title.setObjectName("CardTitle")
        self.detail_title.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.asset_status_label = QLabel()
        self.asset_status_label.setObjectName("SeparationAssetStatus")
        details_header.addWidget(self.detail_title, 1)
        details_header.addWidget(self.asset_status_label)

        self.detail_description = QLabel()
        self.detail_description.setObjectName("MutedText")
        self.detail_description.setWordWrap(True)
        self.detail_description.setMinimumHeight(
            self.detail_description.fontMetrics().lineSpacing() * 2 + 2
        )

        self.custom_model_frame = QFrame()
        self.custom_model_frame.setObjectName("CustomSeparationChoice")
        self.custom_model_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        custom_layout = QVBoxLayout(self.custom_model_frame)
        custom_layout.setContentsMargins(0, 3, 0, 3)
        custom_layout.setSpacing(9)
        self.custom_model_buttons: dict[str, dict[str, FeedbackButton]] = {}
        self.custom_model_groups: dict[str, QButtonGroup] = {}
        self._add_custom_model_row(custom_layout, "Vocal model", "vocal")
        self._add_custom_model_row(
            custom_layout,
            "Instrumental model",
            "instrumental",
        )

        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 2, 0, 0)
        detail_grid.setHorizontalSpacing(16)
        detail_grid.setVerticalSpacing(7)
        self.use_case_value = _detail_row(detail_grid, 0, "Recommended for")
        self.processing_time_value = _detail_row(detail_grid, 1, "Processing time")
        self.model_name, self.model_value = _detail_widgets(
            detail_grid,
            2,
            "Model",
        )
        self.passes_value = _detail_row(detail_grid, 3, "Model runs")
        self.precision_value = _detail_row(detail_grid, 4, "Output precision")
        self.consistency_value = _detail_row(detail_grid, 5, "Mix correction")
        detail_grid.setColumnStretch(1, 1)

        details_layout.addLayout(details_header)
        details_layout.addWidget(self.detail_description)
        details_layout.addWidget(self.custom_model_frame)
        details_layout.addLayout(detail_grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(self.method_control)
        layout.addWidget(details)

        self.select_recipe(self._selected_recipe.recipe_id)

    def _add_custom_model_row(
        self,
        layout: QVBoxLayout,
        title: str,
        role: str,
    ) -> None:
        row = QFrame()
        row.setObjectName("CustomModelRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)
        label = QLabel()
        label.setObjectName("FieldLabel")
        set_translated_text(label, title)
        control = QFrame()
        control.setObjectName("SegmentedControl")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.custom_model_groups[role] = group
        buttons: dict[str, FeedbackButton] = {}
        for recipe in self._custom_model_recipes:
            button = FeedbackButton(_custom_button_label(recipe))
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.clicked.connect(
                lambda _checked=False, current_role=role, recipe_id=recipe.recipe_id: (
                    self._select_custom_model(current_role, recipe_id)
                )
            )
            group.addButton(button)
            buttons[recipe.recipe_id] = button
            control_layout.addWidget(button, 1)
        self.custom_model_buttons[role] = buttons
        row_layout.addWidget(label)
        row_layout.addWidget(control)
        layout.addWidget(row)

    def selected_recipe(self) -> SeparationRecipe:
        return self._selected_recipe

    def select_recipe(self, recipe_id: str, *, emit: bool = False) -> None:
        if recipe_id == CUSTOM_RECIPE.recipe_id:
            recipe = self._current_custom_recipe()
        else:
            if recipe_id == PRECISION_RECIPE.recipe_id:
                recipe_id = VOCAL_MELBAND_RECIPE.recipe_id
            recipe = self._recipes_by_id.get(recipe_id)
        if recipe is not None:
            self._set_selected_recipe(recipe, emit=emit)

    def _select_custom_model(self, role: str, recipe_id: str) -> None:
        if recipe_id not in self._custom_models_by_id:
            return
        if role == "vocal":
            self._custom_vocal_recipe_id = recipe_id
        else:
            self._custom_instrumental_recipe_id = recipe_id
        self._set_selected_recipe(self._current_custom_recipe(), emit=True)

    def _current_custom_recipe(self) -> SeparationRecipe:
        return custom_separation_recipe(
            self._custom_vocal_recipe_id,
            self._custom_instrumental_recipe_id,
        )

    def _set_selected_recipe(self, recipe: SeparationRecipe, *, emit: bool) -> None:
        changed = recipe != self._selected_recipe
        self._selected_recipe = recipe
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
        method_id = CUSTOM_RECIPE.recipe_id if recipe.is_composite else recipe.recipe_id
        if button := self.buttons.get(method_id):
            button.setChecked(True)
        self.custom_model_frame.setVisible(recipe.is_composite)
        self._refresh_custom_buttons()

        status = combine_separation_asset_status(
            self._asset_status_resolver(model) for model in recipe.required_models
        )
        self.detail_title.setText(
            tr("Custom") if method_id == CUSTOM_RECIPE.recipe_id else tr(recipe.label)
        )
        self.detail_description.setText(
            tr(_DESCRIPTION_BY_RECIPE_ID.get(method_id, "Custom separation settings."))
        )
        self.use_case_value.setText(
            tr(_USE_CASE_BY_RECIPE_ID.get(method_id, "Custom workflow"))
        )
        self.model_value.setText(self._model_description(recipe))
        self.model_value.setToolTip(" + ".join(recipe.required_models))
        self.model_name.setVisible(not recipe.is_composite)
        self.model_value.setVisible(not recipe.is_composite)
        model_runs = (
            len({item.recipe_id for item in recipe.component_recipes})
            if recipe.is_composite
            else 1
        )
        self.passes_value.setText(
            tr("{count} model run", count=model_runs)
            if model_runs == 1
            else tr("{count} model runs", count=model_runs)
        )
        self.processing_time_value.setText(self._processing_time(recipe, model_runs))
        self.precision_value.setText("32-bit float" if recipe.float32 else "16-bit")
        self.consistency_value.setText(
            tr("Model defaults")
            if recipe.is_composite
            else tr("Applied") if recipe.mixture_consistency else tr("Not applied")
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

    def _refresh_custom_buttons(self) -> None:
        selected = {
            "vocal": self._custom_vocal_recipe_id,
            "instrumental": self._custom_instrumental_recipe_id,
        }
        for role, buttons in self.custom_model_buttons.items():
            if button := buttons.get(selected[role]):
                button.setChecked(True)

    @staticmethod
    def _model_description(recipe: SeparationRecipe) -> str:
        if not recipe.is_composite:
            return custom_component_label(recipe)
        vocal_recipe, instrumental_recipe = recipe.component_recipes
        return tr(
            "Vocal: {vocal} / Instrumental: {instrumental}",
            vocal=custom_component_label(vocal_recipe),
            instrumental=custom_component_label(instrumental_recipe),
        )

    @staticmethod
    def _processing_time(recipe: SeparationRecipe, model_runs: int) -> str:
        if recipe.recipe_id == FAST_RECIPE.recipe_id:
            return tr("Fast")
        if not recipe.is_composite or model_runs == 1:
            only_recipe = recipe.component_recipes[0] if recipe.is_composite else recipe
            return (
                tr("Fast")
                if only_recipe.recipe_id == FAST_RECIPE.recipe_id
                else tr("Slower")
            )
        return tr("Slowest (two models)")


def _detail_row(layout: QGridLayout, row: int, label: str) -> QLabel:
    return _detail_widgets(layout, row, label)[1]


def _detail_widgets(
    layout: QGridLayout,
    row: int,
    label: str,
) -> tuple[QLabel, QLabel]:
    name = QLabel()
    name.setObjectName("SeparationRecipeField")
    set_translated_text(name, label)
    value = QLabel()
    value.setObjectName("SeparationRecipeValue")
    value.setWordWrap(True)
    value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout.addWidget(name, row, 0)
    layout.addWidget(value, row, 1)
    return name, value


def _custom_button_label(recipe: SeparationRecipe) -> str:
    if recipe.recipe_id == VOCAL_MELBAND_RECIPE.recipe_id:
        return "Kim MelBand"
    return custom_component_label(recipe)
