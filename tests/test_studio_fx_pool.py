from __future__ import annotations

import unittest
import importlib

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.services.i18n import LANGUAGE_KOREAN, set_language

class StudioFxPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        try:
            self.studio_fx_pool = importlib.import_module("jang_app.qt_app.studio_fx_pool")
        except ModuleNotFoundError:
            self.studio_fx_pool = None

    def test_reverb_card_builds_the_studio_effect_drag_payload(self) -> None:
        self.assertIsNotNone(self.studio_fx_pool)
        pool = self.studio_fx_pool.StudioFxPool()

        self.assertEqual(tuple(pool.cards), ("reverb",))
        card = pool.cards["reverb"]
        self.assertEqual(card.effect_kind, "reverb")
        self.assertTrue(card.mime_data().hasFormat(self.studio_fx_pool.STUDIO_EFFECT_MIME))
        self.assertEqual(
            bytes(card.mime_data().data(self.studio_fx_pool.STUDIO_EFFECT_MIME)).decode("utf-8"),
            "reverb",
        )
        pool.close()

    def test_fx_pool_is_expanded_and_has_its_own_scroll_area(self) -> None:
        self.assertIsNotNone(self.studio_fx_pool)
        pool = self.studio_fx_pool.StudioFxPool()
        pool.show()
        self.app.processEvents()

        self.assertTrue(pool.isVisible())
        self.assertIs(pool.scroll.widget(), pool.content)
        self.assertEqual(pool.title_label.text(), "FX")
        pool.close()

    def test_fx_pool_uses_the_studio_theme_contract_and_korean_copy(self) -> None:
        self.assertIsNotNone(self.studio_fx_pool)
        stylesheet = build_stylesheet("dark")

        self.assertIn("QFrame#StudioFxPool", stylesheet)
        self.assertIn("QFrame#StudioFxCard:hover", stylesheet)
        self.assertIn("QLabel#StudioFxCardIcon", stylesheet)

        set_language(LANGUAGE_KOREAN)
        pool = self.studio_fx_pool.StudioFxPool()
        card = pool.cards["reverb"]
        self.assertEqual(card.name_label.text(), "리버브")
        self.assertEqual(card.detail_label.text(), "공간감과 잔향")
        self.assertIn("타임라인 클립", card.toolTip())
        pool.close()


if __name__ == "__main__":
    unittest.main()
