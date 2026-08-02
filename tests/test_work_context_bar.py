from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.work_context_bar import WorkContextBar
from jang_app.services.work_context import WorkContextDisplay


class WorkContextBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_populates_without_signal_and_emits_activated_song(self) -> None:
        bar = WorkContextBar()
        changed = QSignalSpy(bar.song_changed)

        bar.set_songs((("one", "Song One"), ("two", "Song Two")), "one")

        self.assertEqual(bar.selected_song_id(), "one")
        self.assertEqual(changed.count(), 0)
        bar.song_combo.activated.emit(bar.song_combo.findData("two"))
        self.assertEqual(bar.selected_song_id(), "two")
        self.assertEqual(changed.at(0)[0], "two")
        bar.close()

    def test_exact_search_selects_song_and_invalid_search_restores_selection(self) -> None:
        bar = WorkContextBar()
        bar.set_songs((("one", "Song One"), ("two", "Song Two")), "one")
        changed = QSignalSpy(bar.song_changed)

        bar.song_combo.lineEdit().setText("song two")
        bar.song_combo.lineEdit().returnPressed.emit()

        self.assertEqual(bar.selected_song_id(), "two")
        self.assertEqual(changed.at(0)[0], "two")
        bar.song_combo.lineEdit().setText("missing")
        bar.song_combo.lineEdit().returnPressed.emit()
        self.assertEqual(bar.song_combo.currentText(), "Song Two")
        self.assertEqual(changed.count(), 1)
        bar.close()

    def test_empty_context_keeps_global_selector_visible(self) -> None:
        bar = WorkContextBar()

        bar.set_display(WorkContextDisplay(is_active=False))

        self.assertFalse(bar.isHidden())
        self.assertTrue(bar.source_badge.isHidden())
        self.assertTrue(bar.detail_label.isHidden())
        self.assertTrue(bar.state_label.isHidden())
        bar.close()


if __name__ == "__main__":
    unittest.main()
