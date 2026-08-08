from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.separation_recipe_selector import SeparationRecipeSelector
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language
from jang_app.services.separation_assets import SeparationAssetStatus
from jang_app.services.separation_recipe import (
    HIGH_QUALITY_RECIPE,
    MAXIMUM_RECIPE,
    SEPARATION_RECIPES,
)


class SeparationRecipeSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        set_language(LANGUAGE_KOREAN)

    def test_default_recipe_and_details_match_high_quality(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)

        self.assertEqual(selector.selected_recipe(), HIGH_QUALITY_RECIPE)
        self.assertTrue(selector.buttons[HIGH_QUALITY_RECIPE.recipe_id].isChecked())
        self.assertEqual(selector.model_value.text(), HIGH_QUALITY_RECIPE.model)
        self.assertIn(str(HIGH_QUALITY_RECIPE.shifts), selector.passes_value.text())
        self.assertIn("50%", selector.overlap_value.text())
        self.assertIn("321 MB", selector.asset_status_label.text())
        selector.close()

    def test_recipe_buttons_share_one_row_and_equal_width(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)
        selector.resize(420, selector.sizeHint().height())
        selector.show()
        self.app.processEvents()

        buttons = tuple(selector.buttons[recipe.recipe_id] for recipe in SEPARATION_RECIPES)
        top_positions = {button.mapTo(selector, button.rect().topLeft()).y() for button in buttons}
        widths = [button.width() for button in buttons]

        self.assertEqual(len(top_positions), 1)
        self.assertLessEqual(max(widths) - min(widths), 1)
        selector.close()

    def test_selecting_method_updates_details_and_emits_recipe(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)
        changed = QSignalSpy(selector.recipe_changed)

        selector.buttons[MAXIMUM_RECIPE.recipe_id].click()

        self.assertEqual(selector.selected_recipe(), MAXIMUM_RECIPE)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0], MAXIMUM_RECIPE)
        self.assertEqual(selector.model_value.text(), "htdemucs_ft + htdemucs")
        self.assertIn("2", selector.passes_value.text())
        self.assertIn(str(MAXIMUM_RECIPE.shifts), selector.passes_value.text())
        self.assertTrue(selector.buttons[MAXIMUM_RECIPE.recipe_id].isChecked())
        self.assertEqual(sum(button.isChecked() for button in selector.buttons.values()), 1)
        selector.close()

    def test_language_change_updates_buttons_and_dynamic_details(self) -> None:
        selector = SeparationRecipeSelector(asset_status_resolver=_asset_status)

        set_language(LANGUAGE_ENGLISH)
        selector.apply_language()
        self.assertEqual(
            selector.buttons[HIGH_QUALITY_RECIPE.recipe_id].text(),
            "High Quality",
        )
        self.assertEqual(selector.passes_value.text(), "2 passes")

        set_language(LANGUAGE_KOREAN)
        selector.apply_language()
        self.assertEqual(
            selector.buttons[HIGH_QUALITY_RECIPE.recipe_id].text(),
            "고품질",
        )
        self.assertEqual(selector.passes_value.text(), "2회")
        selector.close()


def _asset_status(model: str) -> SeparationAssetStatus:
    if model == "htdemucs":
        return SeparationAssetStatus(model, True, 1, 1, 0)
    return SeparationAssetStatus(model, False, 0, 4, 321 * 1024**2)


if __name__ == "__main__":
    unittest.main()
