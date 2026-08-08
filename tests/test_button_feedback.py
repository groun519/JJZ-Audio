from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.processing_queue_panel import ProcessingQueueButton
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import (
    FeedbackButton,
    InfoPopoverButton,
    WindowTitleBar,
    _TRACK_ICON_SVGS,
    _track_button_palette,
    _window_control_palette,
)
from jang_app.services.processing_queue import ProcessingQueue


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

    def test_window_close_button_is_distinct_before_hover(self) -> None:
        for theme_mode in ("dark", "white"):
            close = _window_control_palette(
                theme_mode,
                "WindowCloseButton",
                True,
                False,
                False,
            )
            minimize = _window_control_palette(
                theme_mode,
                "WindowControlButton",
                True,
                False,
                False,
            )

            with self.subTest(theme_mode=theme_mode):
                self.assertNotEqual(close["background"], minimize["background"])
                self.assertNotEqual(close["icon"], minimize["icon"])

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

    def test_title_bar_contains_processing_queue_button(self) -> None:
        for theme_mode in ("dark", "white"):
            title_bar = WindowTitleBar(
                "JJZero Audio",
                Path(),
                version_text="v0.2.8",
            )
            title_bar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            queue = ProcessingQueue()
            queue_button = ProcessingQueueButton(queue, parent=title_bar.action_widget)
            title_bar.add_action_widget(queue_button)
            queue.start("Test task", progress=25)
            title_bar.setStyleSheet(build_stylesheet(theme_mode))
            title_bar.resize(900, title_bar.height())
            title_bar.show()
            self.app.processEvents()

            button_rect = queue_button.geometry()
            action_rect = title_bar.action_widget.rect()
            with self.subTest(theme_mode=theme_mode):
                self.assertEqual(queue_button.size().toTuple(), (48, 26))
                self.assertTrue(action_rect.contains(button_rect))

            title_bar.close()

    def test_title_bar_version_never_shows_as_an_independent_window(self) -> None:
        unexpected: list[QWidget] = []

        class WindowShowProbe(QObject):
            def eventFilter(self, watched, event):  # noqa: N802
                if (
                    event.type() == QEvent.Type.Show
                    and isinstance(watched, QWidget)
                    and watched.objectName() == "AppVersion"
                    and watched.isWindow()
                ):
                    unexpected.append(watched)
                return False

        probe = WindowShowProbe()
        self.app.installEventFilter(probe)
        try:
            title_bar = WindowTitleBar("JJZero Audio", Path(), version_text="v0.2.5")
            self.app.processEvents()
            self.assertEqual(unexpected, [])
            self.assertIs(title_bar.version_label.parentWidget(), title_bar)
            title_bar.close()
        finally:
            self.app.removeEventFilter(probe)


if __name__ == "__main__":
    unittest.main()
