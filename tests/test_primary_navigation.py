from __future__ import annotations

import unittest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.primary_navigation import (
    NavigationActionButton,
    NavigationItemButton,
    PrimaryNavigationBar,
)


class PrimaryNavigationBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_data_and_export_pages_are_separate_from_the_connected_workflow(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        requested = QSignalSpy(navigation.page_requested)
        settings_requested = QSignalSpy(navigation.settings_requested)
        work_song_changed = QSignalSpy(navigation.work_song_changed)

        navigation.workflow_buttons[1].click()
        navigation.settings_button.click()
        navigation.set_work_songs((("song-1", "Song One"),), "")
        navigation.work_song_selector.select_song("song-1", emit=True)

        self.assertEqual(requested.at(0)[0], 3)
        self.assertEqual(navigation.button_group.checkedId(), 3)
        self.assertTrue(all(isinstance(button, NavigationItemButton) for button in navigation.buttons))
        self.assertTrue(all(button.objectName() == "NavigationItemButton" for button in navigation.buttons))
        self.assertEqual(navigation.height(), 66)
        self.assertTrue(all((button.width(), button.height()) == (112, 38) for button in navigation.buttons))
        self.assertEqual(navigation.data_divider.width(), 1)
        self.assertEqual(navigation.data_divider.height(), 20)
        self.assertEqual(navigation.export_divider.width(), 1)
        self.assertEqual(settings_requested.count(), 1)
        self.assertEqual(work_song_changed.at(0)[0], "song-1")
        self.assertEqual(
            (
                navigation.work_song_selector.sizeHint().width(),
                navigation.work_song_selector.sizeHint().height(),
            ),
            (344, 50),
        )
        self.assertIsInstance(navigation.settings_button, NavigationActionButton)
        self.assertEqual((navigation.settings_button.width(), navigation.settings_button.height()), (38, 38))
        self.assertNotIn(navigation.settings_button, navigation.buttons)
        self.assertEqual(navigation.button_group.checkedId(), 3)
        navigation.set_current_page(0)
        self.assertTrue(navigation.leading_buttons[0].isChecked())
        navigation.close()

    def test_workflow_page_can_be_locked_with_an_explanation(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        requested = QSignalSpy(navigation.page_requested)

        navigation.set_page_enabled(2, False, disabled_tooltip="Select a work song")
        navigation.workflow_buttons[0].click()

        self.assertFalse(navigation.workflow_buttons[0].isEnabled())
        self.assertEqual(navigation.workflow_buttons[0].toolTip(), "Select a work song")
        self.assertEqual(requested.count(), 0)

        navigation.set_page_enabled(2, True, disabled_tooltip="Select a work song")
        self.assertTrue(navigation.workflow_buttons[0].isEnabled())
        self.assertEqual(navigation.workflow_buttons[0].toolTip(), "")
        navigation.close()

    def test_page_submenu_opens_on_hover_and_requests_option(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.set_page_options(
            2,
            (("audio", "Audio Separation"), ("vocal", "Vocal Separation")),
            selected_option="audio",
        )
        page_requested = QSignalSpy(navigation.page_requested)
        option_requested = QSignalSpy(navigation.page_option_requested)

        navigation.resize(1500, 66)
        navigation.show()
        self.app.processEvents()
        QTest.mouseMove(
            navigation.workflow_buttons[0],
            navigation.workflow_buttons[0].rect().center(),
        )
        self.app.processEvents()
        menu = navigation._page_menus[2]

        QTest.qWait(420)
        self.assertTrue(menu.isVisible())
        self.assertTrue(bool(menu.property("allowTopLevelWindow")))
        self.assertGreater(
            menu.pos().y(),
            navigation.workflow_buttons[0]
            .mapToGlobal(navigation.workflow_buttons[0].rect().bottomLeft())
            .y(),
        )
        QTest.mouseMove(menu, menu.rect().center())
        QTest.qWait(420)
        self.assertTrue(menu.isVisible())
        navigation._page_menu_actions[2]["vocal"].click()

        self.assertEqual(page_requested.count(), 0)
        self.assertEqual(tuple(option_requested.at(0)), (2, "vocal"))
        self.assertTrue(navigation._page_menu_actions[2]["vocal"].isChecked())
        self.assertTrue(navigation.workflow_buttons[0]._has_submenu)
        menu.close()
        navigation.close()

    def test_page_click_uses_current_option_without_opening_submenu(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.set_page_options(
            2,
            (("audio", "Audio Separation"), ("vocal", "Vocal Separation")),
            selected_option="vocal",
        )
        requested = QSignalSpy(navigation.page_requested)

        navigation.resize(1500, 66)
        navigation.show()
        self.app.processEvents()
        QCursor.setPos(navigation.mapToGlobal(QPoint(0, 0)))
        self.app.processEvents()
        navigation.workflow_buttons[0].click()
        self.app.processEvents()

        self.assertEqual(tuple(requested.at(0)), (2,))
        self.assertFalse(navigation._page_menus[2].isVisible())
        self.assertTrue(navigation._page_menu_actions[2]["vocal"].isChecked())
        navigation.close()

    def test_disabled_page_option_remains_visible_without_requesting_navigation(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.set_page_options(
            2,
            (
                ("audio", "Audio Separation"),
                ("vocal", "Vocal Separation · In development"),
            ),
            selected_option="audio",
        )
        navigation.set_page_option_enabled(
            2,
            "vocal",
            False,
            disabled_tooltip="Singer separation model is not connected yet.",
        )
        requested = QSignalSpy(navigation.page_option_requested)
        vocal_option = navigation._page_menu_actions[2]["vocal"]

        vocal_option.click()

        self.assertFalse(vocal_option.isEnabled())
        self.assertFalse(vocal_option.isChecked())
        self.assertEqual(
            vocal_option.toolTip(),
            "Singer separation model is not connected yet.",
        )
        self.assertEqual(requested.count(), 0)
        self.assertTrue(navigation._page_menu_actions[2]["audio"].isChecked())
        navigation.close()

    def test_page_submenu_closes_after_pointer_leaves_button_and_menu(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.set_page_options(
            2,
            (("audio", "Audio Separation"), ("vocal", "Vocal Separation")),
            selected_option="audio",
        )

        navigation.resize(1500, 66)
        navigation.show()
        self.app.processEvents()
        button = navigation.workflow_buttons[0]
        menu = navigation._page_menus[2]
        QTest.mouseMove(button, button.rect().center())
        self.app.processEvents()
        self.assertTrue(menu.isVisible())

        QTest.mouseMove(menu, menu.rect().center())
        self.app.processEvents()
        QCursor.setPos(navigation.mapToGlobal(QPoint(0, 0)))
        self.app.processEvents()
        QTest.qWait(180)

        self.assertFalse(menu.isVisible())
        navigation.close()

    def test_work_song_card_does_not_overlap_navigation_at_minimum_window_width(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.resize(1180, 66)
        navigation.show()
        self.app.processEvents()

        selector_right = navigation.work_song_selector.mapTo(
            navigation,
            navigation.work_song_selector.rect().bottomRight(),
        ).x()
        first_button_left = navigation.leading_buttons[0].mapTo(
            navigation,
            navigation.leading_buttons[0].rect().topLeft(),
        ).x()

        self.assertLess(
            selector_right,
            first_button_left,
        )
        navigation.close()

    def test_channel_group_stays_centered_with_the_work_song_card_visible(self) -> None:
        navigation = PrimaryNavigationBar(
            (("Library", 0), ("Models", 1)),
            (("Separation", 2), ("Conversion", 3), ("Studio", 4)),
            ("Export", 5),
        )
        navigation.resize(1500, 66)
        navigation.show()
        self.app.processEvents()

        channel_center = navigation.channel_slot.mapTo(
            navigation,
            navigation.channel_slot.rect().center(),
        ).x()

        self.assertLessEqual(abs(channel_center - navigation.rect().center().x()), 1)
        navigation.close()


if __name__ == "__main__":
    unittest.main()
