from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QWidget

from jang_app.config import APP_ICON_PATH
from jang_app.qt_app.startup_splash import StartupSplash
from jang_app.version import __version__


class StartupSplashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_stage_progress_and_error_state_are_visible(self) -> None:
        splash = StartupSplash(APP_ICON_PATH)
        splash.set_stage("Loading workspace modules", 0.48)

        self.assertEqual((splash.width(), splash.height()), (720, 400))
        self.assertEqual(splash.detail_label.text(), "Loading workspace modules")
        self.assertAlmostEqual(splash.progress, 0.48)
        self.assertTrue(splash.close_button.isHidden())
        self.assertEqual(splash.descriptor_label.text(), "AUDIO WORKSPACE")
        self.assertEqual(splash.version_label.text(), f"v{__version__}")
        self.assertEqual(splash.version_label.objectName(), "SplashVersion")
        self.assertEqual(splash.version_label.x(), splash.subtitle_label.x())
        self.assertGreater(splash.version_label.y(), splash.subtitle_label.geometry().bottom())
        self.assertNotIn("border", splash.version_label.styleSheet())
        self.assertNotIn("background: #", splash.version_label.styleSheet())

        splash.show_error("Broken runtime")

        self.assertEqual(splash.stage_label.text(), "STARTUP FAILED")
        self.assertEqual(splash.detail_label.text(), "Broken runtime")
        self.assertFalse(splash.close_button.isHidden())
        splash.close()

    def test_finish_shows_main_window(self) -> None:
        splash = StartupSplash(APP_ICON_PATH)
        window = QWidget()

        splash.show_centered()
        splash.finish(window)
        self.app.processEvents()

        self.assertTrue(window.isVisible())
        self.assertEqual(splash.stage_label.text(), "READY")
        window.close()
        splash.close()


if __name__ == "__main__":
    unittest.main()
