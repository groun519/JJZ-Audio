from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from jang_app.config import GOOGLE_ICON_PATH
from jang_app.qt_app.google_account_button import GoogleAccountButton, _quota_detail, _quota_visual
from jang_app.services.google_drive import GoogleDriveQuota
from jang_app.services.google_oauth import GoogleAccount


class GoogleAccountButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_disconnected_click_requests_account_connection(self) -> None:
        button = GoogleAccountButton(GOOGLE_ICON_PATH)
        requested = QSignalSpy(button.connect_requested)

        button.click()

        self.assertEqual(requested.count(), 1)
        self.assertIsNone(button.account)
        button.close()

    def test_connected_account_updates_visual_state_and_identity(self) -> None:
        button = GoogleAccountButton(GOOGLE_ICON_PATH)
        account = GoogleAccount("subject", "user@example.com", "User")

        disconnected_spread = _maximum_channel_spread(button)

        button.set_account(account)

        self.assertEqual(button.account, account)
        self.assertTrue(button.property("connected"))
        self.assertIsNotNone(button.menu())
        self.assertIn("user@example.com", button.toolTip())
        self.assertLessEqual(disconnected_spread, 1)
        self.assertGreater(_maximum_channel_spread(button), 40)
        button.close()

    def test_unavailable_configuration_disables_login(self) -> None:
        button = GoogleAccountButton(GOOGLE_ICON_PATH)

        button.set_unavailable("OAuth client is missing")

        self.assertFalse(button.isEnabled())
        self.assertEqual(button.toolTip(), "OAuth client is missing")
        button.close()

    def test_quota_visual_uses_remaining_capacity_thresholds(self) -> None:
        healthy = GoogleDriveQuota(100, 79, 50)
        warning = GoogleDriveQuota(100, 80, 50)
        danger = GoogleDriveQuota(100, 90, 50)

        self.assertEqual(_quota_visual(healthy), (0.79, "healthy"))
        self.assertEqual(_quota_visual(warning), (0.8, "warning"))
        self.assertEqual(_quota_visual(danger), (0.9, "danger"))

    def test_quota_detail_shows_available_and_total_capacity(self) -> None:
        quota = GoogleDriveQuota(15 * 1024**3, 12 * 1024**3, 10 * 1024**3)

        detail = _quota_detail(quota)

        self.assertIn("3.0 GB", detail)
        self.assertIn("15.0 GB", detail)

    def test_connected_button_second_click_closes_account_menu(self) -> None:
        button = GoogleAccountButton(GOOGLE_ICON_PATH)
        button.set_account(GoogleAccount("subject", "user@example.com", "User"))
        button.show()

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(button.menu().isVisible())

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(button.menu().isVisible())
        button.close()

def _maximum_channel_spread(button: GoogleAccountButton) -> int:
    image = button.icon().pixmap(button.iconSize()).toImage()
    spreads = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 32:
                channels = (color.red(), color.green(), color.blue())
                spreads.append(max(channels) - min(channels))
    return max(spreads, default=0)


if __name__ == "__main__":
    unittest.main()
