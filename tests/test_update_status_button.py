from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.update_status_button import (
    STATE_DOWNLOADING,
    STATE_FAILED,
    STATE_READY,
    UpdateStatusButton,
    update_button_position,
)
from jang_app.services.i18n import tr


class UpdateStatusButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_tracks_available_download_ready_and_failed_states(self) -> None:
        button = UpdateStatusButton()
        button.set_available("0.2.2")
        self.assertIn("0.2.2", button.accessibleName())

        button.set_available("0.2.2", runtime_only=True)
        self.assertEqual(button.accessibleName(), tr("GPU runtime update"))

        button.set_downloading(35)
        self.assertEqual(button.state, STATE_DOWNLOADING)
        self.assertIn("35", button.accessibleName())

        button.set_ready()
        self.assertEqual(button.state, STATE_READY)
        button.set_failed()
        self.assertEqual(button.state, STATE_FAILED)

    def test_stacks_above_the_lowest_left_surface(self) -> None:
        self.assertEqual(update_button_position(600, 44), (16, 540))
        self.assertEqual(
            update_button_position(600, 44, anchor_tops=(490, 410)),
            (16, 356),
        )


if __name__ == "__main__":
    unittest.main()
