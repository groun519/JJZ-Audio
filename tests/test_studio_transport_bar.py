from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_transport_bar import StudioTransportBar


class StudioTransportBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_transport_and_timeline_tools_share_one_fixed_bar(self) -> None:
        bar = StudioTransportBar()
        play_toggled = QSignalSpy(bar.play_toggled)

        bar.set_queue(90_000)
        bar.transport.play_button.click()

        self.assertEqual(bar.height(), 56)
        self.assertEqual(bar.transport.time_label.text(), "00:00 / 01:30")
        self.assertEqual(play_toggled.count(), 1)
        bar.close()

    def test_programmatic_zoom_update_does_not_emit_edit_signal(self) -> None:
        bar = StudioTransportBar()
        changed = QSignalSpy(bar.zoom_changed)

        bar.set_zoom(12)

        self.assertEqual(bar.zoom_slider.value(), 12)
        self.assertEqual(changed.count(), 0)
        bar.close()

    def test_split_button_toggles_persistent_cut_tool_only_when_available(self) -> None:
        bar = StudioTransportBar()
        changed = QSignalSpy(bar.split_mode_changed)

        bar.split_button.click()
        self.assertEqual(changed.count(), 0)

        bar.set_split_enabled(True)
        bar.split_shortcut.activated.emit()
        self.assertTrue(bar.split_button.isChecked())
        self.assertEqual(changed.count(), 1)
        self.assertTrue(changed.at(0)[0])

        bar.exit_split_shortcut.activated.emit()
        self.assertFalse(bar.split_button.isChecked())
        self.assertEqual(changed.count(), 2)
        self.assertFalse(changed.at(1)[0])
        bar.close()

    def test_undo_redo_buttons_follow_history_availability(self) -> None:
        bar = StudioTransportBar()
        undo_requested = QSignalSpy(bar.undo_requested)
        redo_requested = QSignalSpy(bar.redo_requested)

        bar.undo_button.click()
        bar.redo_button.click()
        self.assertEqual(undo_requested.count(), 0)
        self.assertEqual(redo_requested.count(), 0)

        bar.set_history_available(True, True)
        bar.undo_button.click()
        bar.redo_button.click()

        self.assertEqual(undo_requested.count(), 1)
        self.assertEqual(redo_requested.count(), 1)
        bar.close()


if __name__ == "__main__":
    unittest.main()
