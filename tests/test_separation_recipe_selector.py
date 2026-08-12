from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.separation_recipe_selector import SeparationRecipeSelector
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language
from jang_app.services.separation_assets import SeparationAssetStatus
from jang_app.services.separation_recipe import (
    CUSTOM_RECIPE,
    FAST_RECIPE,
    SEPARATION_RECIPES,
    VOCAL_MELBAND_RECIPE,
)


class SeparationRecipeSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language(LANGUAGE_KOREAN)

    def tearDown(self) -> None:
        set_language(LANGUAGE_KOREAN)

    def test_default_recipe_is_the_kim_precision_preset(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)

        self.assertEqual(selector.selected_recipe(), VOCAL_MELBAND_RECIPE)
        self.assertTrue(
            selector.buttons[VOCAL_MELBAND_RECIPE.recipe_id].isChecked()
        )
        self.assertEqual(selector.model_value.text(), "Vocal MelBand (Kim)")
        self.assertTrue(selector.custom_model_frame.isHidden())
        self.assertIn("871 MB", selector.asset_status_label.text())
        selector.close()

    def test_three_method_buttons_share_one_row_and_equal_width(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)
        selector.resize(420, selector.sizeHint().height())
        selector.show()
        self.app.processEvents()

        buttons = tuple(selector.buttons[recipe.recipe_id] for recipe in SEPARATION_RECIPES)
        top_positions = {
            button.mapTo(selector, button.rect().topLeft()).y() for button in buttons
        }
        widths = [button.width() for button in buttons]

        self.assertEqual(len(buttons), 3)
        self.assertEqual(len(top_positions), 1)
        self.assertLessEqual(max(widths) - min(widths), 1)
        self.assertEqual(selector.layout().count(), 2)
        self.assertIs(selector.layout().itemAt(0).widget(), selector.method_control)
        selector.close()

    def test_custom_method_selects_vocal_and_instrumental_independently(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)
        changed = QSignalSpy(selector.recipe_changed)

        selector.buttons[CUSTOM_RECIPE.recipe_id].click()
        recipe = selector.selected_recipe()

        self.assertTrue(recipe.is_composite)
        self.assertEqual(recipe.vocal_recipe_id, VOCAL_MELBAND_RECIPE.recipe_id)
        self.assertEqual(recipe.instrumental_recipe_id, FAST_RECIPE.recipe_id)
        self.assertFalse(selector.custom_model_frame.isHidden())
        self.assertEqual(len(recipe.required_models), 2)

        selector.custom_model_buttons["instrumental"][
            VOCAL_MELBAND_RECIPE.recipe_id
        ].click()
        recipe = selector.selected_recipe()

        self.assertEqual(recipe.vocal_recipe_id, recipe.instrumental_recipe_id)
        self.assertEqual(recipe.required_models, (VOCAL_MELBAND_RECIPE.model,))
        self.assertIn("1", selector.passes_value.text())
        self.assertEqual(changed.count(), 2)
        selector.close()

    def test_selecting_fast_updates_details_and_emits_recipe(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)
        changed = QSignalSpy(selector.recipe_changed)

        selector.buttons[FAST_RECIPE.recipe_id].click()

        self.assertEqual(selector.selected_recipe(), FAST_RECIPE)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0], FAST_RECIPE)
        self.assertEqual(selector.model_value.text(), "HTDemucs")
        self.assertTrue(selector.custom_model_frame.isHidden())
        selector.close()

    def test_language_change_updates_all_method_buttons(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)

        set_language(LANGUAGE_ENGLISH)
        selector.apply_language()
        self.assertEqual(
            selector.buttons[VOCAL_MELBAND_RECIPE.recipe_id].text(),
            "Precision Separation",
        )
        self.assertEqual(
            selector.buttons[CUSTOM_RECIPE.recipe_id].text(),
            "Custom",
        )

        set_language(LANGUAGE_KOREAN)
        selector.apply_language()
        self.assertEqual(
            selector.buttons[CUSTOM_RECIPE.recipe_id].text(),
            "커스텀",
        )
        selector.close()


def _asset_status(model: str) -> SeparationAssetStatus:
    if model == FAST_RECIPE.model:
        return SeparationAssetStatus(model, True, 1, 1, 0)
    if model == VOCAL_MELBAND_RECIPE.model:
        return SeparationAssetStatus(model, False, 0, 2, 913_107_868)
    return SeparationAssetStatus(model, False, 0, 1, 610 * 1024**2)


if __name__ == "__main__":
    unittest.main()
