from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_master_panel import StudioMasterPanel
from jang_app.services.studio_session import StudioMasterState


class StudioMasterPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_controls_emit_a_complete_processing_state(self) -> None:
        panel = StudioMasterPanel()
        changed = QSignalSpy(panel.processing_changed)

        panel.gain_slider.setValue(6)
        panel.width_slider.setValue(140)

        self.assertEqual(panel.state(), StudioMasterState(gain_db=6, stereo_width_percent=140))
        self.assertEqual(changed.at(changed.count() - 1)[0], panel.state())
        panel.close()

    def test_reset_emits_one_default_state(self) -> None:
        panel = StudioMasterPanel()
        panel.set_state(StudioMasterState(-12, 40))
        changed = QSignalSpy(panel.processing_changed)

        panel.reset_button.click()

        self.assertEqual(panel.state(), StudioMasterState())
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0], StudioMasterState())
        panel.close()


if __name__ == "__main__":
    unittest.main()
