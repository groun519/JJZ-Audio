from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.config import GOOGLE_ICON_PATH
from jang_app.qt_app.google_account_button import GoogleAccountButton
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
