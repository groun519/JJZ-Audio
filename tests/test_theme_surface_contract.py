from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QScrollArea

from jang_app.qt_app.theme import build_stylesheet, theme_tokens
from jang_app.qt_app.widgets import (
    SurfaceFrame,
    TransparentContainer,
    attach_transparent_scroll_widget,
)


class ThemeSurfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_layout_container_does_not_cover_parent_surface(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        try:
            for theme_mode in ("dark", "white"):
                with self.subTest(theme_mode=theme_mode):
                    self.app.setStyleSheet(build_stylesheet(theme_mode))
                    host = SurfaceFrame("raised")
                    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    host.resize(80, 60)
                    child = TransparentContainer(host)
                    child.setGeometry(20, 15, 40, 30)
                    host.show()
                    self.app.processEvents()

                    image = host.grab().toImage()
                    expected = QColor(theme_tokens(theme_mode)["raised"])
                    self.assertEqual(image.pixelColor(5, 5), expected)
                    self.assertEqual(image.pixelColor(30, 25), expected)
                    host.close()
        finally:
            self.app.setStyleSheet(previous_stylesheet)

    def test_dialog_root_keeps_explicit_window_background(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        try:
            for theme_mode in ("dark", "white"):
                with self.subTest(theme_mode=theme_mode):
                    self.app.setStyleSheet(build_stylesheet(theme_mode))
                    dialog = QDialog()
                    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    dialog.resize(40, 40)
                    dialog.show()
                    self.app.processEvents()

                    image = dialog.grab().toImage()
                    expected = QColor(theme_tokens(theme_mode)["background"])
                    self.assertEqual(image.pixelColor(20, 20), expected)
                    dialog.close()
        finally:
            self.app.setStyleSheet(previous_stylesheet)

    def test_scroll_viewport_does_not_expose_the_platform_base_palette(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        try:
            for theme_mode in ("dark", "white"):
                with self.subTest(theme_mode=theme_mode):
                    self.app.setStyleSheet(build_stylesheet(theme_mode))
                    host = SurfaceFrame("raised")
                    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    host.resize(100, 80)
                    scroll = QScrollArea(host)
                    scroll.setGeometry(10, 10, 80, 60)
                    content = TransparentContainer()
                    content.setMinimumSize(60, 40)
                    attach_transparent_scroll_widget(scroll, content)
                    host.show()
                    self.app.processEvents()

                    image = host.grab().toImage()
                    expected = QColor(theme_tokens(theme_mode)["raised"])
                    self.assertEqual(image.pixelColor(20, 20), expected)
                    self.assertEqual(image.pixelColor(80, 60), expected)
                    host.close()
        finally:
            self.app.setStyleSheet(previous_stylesheet)

    def test_base_widget_rule_does_not_define_an_opaque_background(self) -> None:
        stylesheet = build_stylesheet("dark")
        base_rule = stylesheet.split("QLabel", 1)[0]

        self.assertNotIn("background:", base_rule.split("QMainWindow", 1)[0])
        self.assertIn('QWidget[surfaceRole="transparent"]', stylesheet)
        self.assertIn('QFrame[surfaceRole="raised"]', stylesheet)


if __name__ == "__main__":
    unittest.main()
