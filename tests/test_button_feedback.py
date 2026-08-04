from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import FeedbackButton, WindowTitleBar, _track_button_palette


class ButtonFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_pointer_press_is_visible_but_click_still_happens_on_release(self) -> None:
        button = FeedbackButton("Action")
        button.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        button.resize(120, 40)
        button.show()
        self.app.processEvents()
        clicked = QSignalSpy(button.clicked)

        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())

        self.assertTrue(button.isDown())
        self.assertEqual(button.property("pointerState"), "pressed")
        self.assertEqual(clicked.count(), 0)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        self.assertFalse(button.isDown())
        self.assertEqual(button.property("pointerState"), "hover")
        self.assertEqual(clicked.count(), 1)
        self.assertFalse(button.hasFocus())
        button.close()

    def test_keyboard_focus_is_distinct_from_pointer_focus(self) -> None:
        button = FeedbackButton("Action")
        button.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        button.resize(120, 40)
        button.show()
        focus_event = QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
        QApplication.sendEvent(button, focus_event)

        self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.assertTrue(button.property("keyboardFocus"))
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())

        self.assertFalse(button.property("keyboardFocus"))
        button.close()

    def test_icon_button_pointer_states_use_distinct_colors(self) -> None:
        for theme_mode in ("dark", "white"):
            normal = _track_button_palette(theme_mode, False, True, False, False)
            hovered = _track_button_palette(theme_mode, False, True, True, False)
            pressed = _track_button_palette(theme_mode, False, True, True, True)
            checked = _track_button_palette(theme_mode, True, True, False, False)
            checked_pressed = _track_button_palette(theme_mode, True, True, True, True)

            with self.subTest(theme_mode=theme_mode):
                self.assertNotEqual(normal["background"], hovered["background"])
                self.assertNotEqual(hovered["background"], pressed["background"])
                self.assertNotEqual(checked["background"], checked_pressed["background"])

    def test_title_bar_language_button_keeps_compact_outer_size(self) -> None:
        for theme_mode in ("dark", "white"):
            button = FeedbackButton("KR" if theme_mode == "dark" else "EN")
            button.setObjectName("TitleBarLanguageButton")
            button.setStyleSheet(build_stylesheet(theme_mode))
            button.ensurePolished()

            with self.subTest(theme_mode=theme_mode):
                self.assertEqual((button.sizeHint().width(), button.sizeHint().height()), (42, 26))

            button.close()

    def test_title_bar_does_not_clip_action_buttons(self) -> None:
        for theme_mode in ("dark", "white"):
            title_bar = WindowTitleBar("JJZero Audio", Path())
            title_bar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            title_bar.setStyleSheet(build_stylesheet(theme_mode))
            language_button = FeedbackButton("KR" if theme_mode == "dark" else "EN")
            language_button.setObjectName("TitleBarLanguageButton")
            language_button.setFixedSize(42, 26)
            title_bar.add_action_widget(language_button)
            title_bar.resize(900, title_bar.height())
            title_bar.show()
            self.app.processEvents()

            with self.subTest(theme_mode=theme_mode):
                self.assertGreaterEqual(title_bar.action_widget.height(), language_button.height())

            title_bar.close()


if __name__ == "__main__":
    unittest.main()
