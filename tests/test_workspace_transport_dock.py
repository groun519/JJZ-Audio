from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.workspace_transport_dock import WorkspaceTransportDock


class WorkspaceTransportDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selector_and_transport_share_one_dock(self) -> None:
        dock = WorkspaceTransportDock()
        changed = QSignalSpy(dock.song_changed)
        play_toggled = QSignalSpy(dock.play_toggled)

        dock.set_songs((("one", "Song One"), ("two", "Song Two")), "one")
        dock.set_queue(60_000)
        dock.song_combo.activated.emit(dock.song_combo.findData("two"))
        dock.transport.play_button.click()

        self.assertEqual(dock.selected_song_id(), "two")
        self.assertEqual(changed.at(0)[0], "two")
        self.assertEqual(play_toggled.count(), 1)
        self.assertEqual(dock.transport.time_label.text(), "00:00 / 01:00")
        dock.close()

    def test_controls_are_ordered_in_one_compact_row(self) -> None:
        dock = WorkspaceTransportDock()
        dock.set_songs((("one", "Song One"),), "one")
        dock.set_queue(60_000)
        dock.resize(1180, dock.height())
        dock.show()
        self.app.processEvents()

        controls = (
            dock.transport.play_button,
            dock.song_combo,
            dock.transport.slider,
            dock.transport.time_label,
        )
        positions = tuple(control.mapTo(dock, control.rect().topLeft()).x() for control in controls)

        self.assertEqual(dock.height(), 58)
        self.assertEqual(positions, tuple(sorted(positions)))
        dock.close()

    def test_selector_retains_width_and_full_title_tooltip(self) -> None:
        dock = WorkspaceTransportDock()
        long_title = "A very long work song title that should remain searchable"

        dock.set_songs((("one", long_title),), "one")
        dock.resize(1180, dock.height())
        dock.show()
        self.app.processEvents()

        self.assertGreaterEqual(dock.song_combo.minimumWidth(), 360)
        self.assertEqual(dock.song_combo.toolTip(), long_title)
        self.assertEqual(dock.song_combo.itemData(1, Qt.ItemDataRole.ToolTipRole), long_title)
        dock.close()

    def test_transport_button_fits_inside_the_fixed_dock_height(self) -> None:
        for theme_mode in ("dark", "white"):
            dock = WorkspaceTransportDock()
            dock.setStyleSheet(build_stylesheet(theme_mode))
            dock.resize(1180, dock.height())
            dock.show()
            self.app.processEvents()

            button = dock.transport.play_button
            button_bottom = button.geometry().bottom()
            transport_bottom = dock.transport.contentsRect().bottom()

            with self.subTest(theme_mode=theme_mode):
                self.assertGreaterEqual(dock.height(), dock.minimumSizeHint().height())
                self.assertLessEqual(button_bottom, transport_bottom)

            dock.close()


if __name__ == "__main__":
    unittest.main()
