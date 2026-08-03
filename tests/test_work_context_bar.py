from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
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

    def test_selector_keeps_priority_width_and_full_title_tooltips(self) -> None:
        bar = WorkContextBar()
        long_title = "A very long work song title that should not reduce the selector width"

        bar.set_songs((("one", long_title),), "one")
        bar.resize(1180, 52)
        bar.show()
        self.app.processEvents()

        self.assertGreaterEqual(bar.song_combo.minimumWidth(), 360)
        self.assertEqual(bar.song_combo.toolTip(), long_title)
        self.assertEqual(
            bar.song_combo.itemData(1, Qt.ItemDataRole.ToolTipRole),
            long_title,
        )
        self.assertEqual(bar.detail_label.width(), 180)
        self.assertEqual(bar.state_label.width(), 86)
        bar.close()

    def test_popup_is_never_narrower_than_the_selector(self) -> None:
        bar = WorkContextBar()
        bar.set_songs((("one", "Song One"),), "one")
        bar.song_combo.resize(480, 32)

        bar.song_combo.showPopup()
        self.app.processEvents()

        self.assertGreaterEqual(bar.song_combo.view().minimumWidth(), 480)
        bar.song_combo.hidePopup()
        bar.close()


if __name__ == "__main__":
    unittest.main()
