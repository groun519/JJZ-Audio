from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import (
    FeedbackButton,
    InfoPopoverButton,
    WindowTitleBar,
    _TRACK_ICON_SVGS,
    _track_button_palette,
)


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

    def test_every_registered_icon_is_valid_svg(self) -> None:
        for name, template in _TRACK_ICON_SVGS.items():
            renderer = QSvgRenderer(
                QByteArray(template.replace("{color}", "#ffffff").encode("utf-8"))
            )
            with self.subTest(name=name):
                self.assertTrue(renderer.isValid())

    def test_title_bar_language_button_keeps_compact_outer_size(self) -> None:
        for theme_mode in ("dark", "white"):
            button = FeedbackButton("KR" if theme_mode == "dark" else "EN")
            button.setObjectName("TitleBarLanguageButton")
            button.setStyleSheet(build_stylesheet(theme_mode))
            button.ensurePolished()

            with self.subTest(theme_mode=theme_mode):
                self.assertEqual((button.sizeHint().width(), button.sizeHint().height()), (42, 26))

            button.close()

    def test_info_popover_exposes_compact_reusable_help_content(self) -> None:
        button = InfoPopoverButton()
        button.set_content(
            "Batch Size",
            "Controls memory usage.",
            "Current recommendation: 4",
        )

        self.assertEqual((button.width(), button.height()), (18, 18))
        self.assertIn("<b>Batch Size</b>", button.toolTip())
        self.assertIn("Controls memory usage.", button.toolTip())
        self.assertIn("Current recommendation: 4", button.toolTip())
        button.close()

    def test_title_bar_does_not_clip_action_buttons(self) -> None:
        for theme_mode in ("dark", "white"):
            title_bar = WindowTitleBar(
                "JJZero Audio",
                Path(),
                version_text="v0.2.5",
            )
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
                self.assertEqual(title_bar.version_label.text(), "v0.2.5")
                self.assertEqual(title_bar.version_label.objectName(), "AppVersion")
                self.assertTrue(title_bar.version_label.isVisible())

            title_bar.close()


if __name__ == "__main__":
    unittest.main()
