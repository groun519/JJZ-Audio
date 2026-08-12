from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.navigation_work_song_selector import NavigationWorkSongSelector
from jang_app.services.i18n import tr


class NavigationWorkSongSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_and_selected_work_song_share_one_large_card(self) -> None:
        selector = NavigationWorkSongSelector()
        selector.set_songs((("one", "Song One"), ("two", "Song Two")), "")

        self.assertEqual(selector.currentText(), tr("No work song"))
        self.assertEqual(selector.sizeHint().width(), 344)
        self.assertEqual(selector.height(), 50)

        selector.select_song("two")

        self.assertEqual(selector.selected_song_id(), "two")
        self.assertEqual(selector.currentText(), "Song Two")
        self.assertEqual(selector.toolTip(), "Song Two")
        selector.close()

    def test_card_selection_emits_the_existing_work_song_id(self) -> None:
        selector = NavigationWorkSongSelector()
        changed = QSignalSpy(selector.song_changed)
        selector.set_songs((("one", "Song One"),), "")

        selector.select_song("one", emit=True)

        self.assertEqual(changed.at(0)[0], "one")
        selector.close()

    def test_loading_state_is_visible_on_the_card(self) -> None:
        selector = NavigationWorkSongSelector()
        selector.set_songs((("one", "Song One"),), "one")

        selector.set_loading(True)

        self.assertTrue(selector.is_loading())
        self.assertTrue(selector._loading_timer.isActive())
        selector.set_loading(False)
        selector.close()

    def test_popup_has_an_explicit_close_action(self) -> None:
        selector = NavigationWorkSongSelector()
        selector.set_songs((("one", "Song One"),), "one")
        selector.show()
        selector.show_selector()
        self.app.processEvents()

        selector._popup.close_button.click()

        self.assertFalse(selector._popup.isVisible())
        selector.close()

    def test_anchor_click_after_popup_dismissal_does_not_reopen_it(self) -> None:
        selector = NavigationWorkSongSelector()
        selector.set_songs((("one", "Song One"),), "one")
        selector._on_popup_closed(True)

        selector.show_selector()

        self.assertFalse(selector._popup.isVisible())
        selector.close()


if __name__ == "__main__":
    unittest.main()
