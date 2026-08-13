from __future__ import annotations

import unittest

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.workspace_splitter import (
    SoftWorkspaceSplitterHandle,
    create_workspace_splitter,
)


class WorkspaceSplitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_builds_draggable_non_collapsible_panels(self) -> None:
        panels = (QWidget(), QWidget())

        splitter = create_workspace_splitter(
            panels,
            object_name="TestWorkspaceSplitter",
            sizes=(300, 900),
            stretch_factors=(0, 1),
        )

        self.assertEqual(splitter.count(), 2)
        self.assertEqual(splitter.handleWidth(), 6)
        self.assertEqual(splitter.property("workspaceSplitter"), True)
        self.assertIsInstance(splitter.handle(1), SoftWorkspaceSplitterHandle)
        self.assertEqual(
            splitter.handle(1).cursor().shape(),
            Qt.CursorShape.SplitHCursor,
        )
        self.assertFalse(splitter.isCollapsible(0))
        self.assertFalse(splitter.isCollapsible(1))
        splitter.resize(1_200, 400)
        splitter.show()
        self.app.processEvents()
        splitter.moveSplitter(500, 1)
        self.app.processEvents()
        self.assertGreaterEqual(splitter.sizes()[0], 490)
        splitter.close()

    def test_handle_fades_in_on_hover_without_changing_hit_width(self) -> None:
        splitter = create_workspace_splitter(
            (QWidget(), QWidget()),
            object_name="AnimatedWorkspaceSplitter",
        )
        splitter.resize(800, 400)
        splitter.show()
        self.app.processEvents()
        handle = splitter.handle(1)
        resting = handle.visual_strength()

        handle.enterEvent(
            QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2))
        )
        QTest.qWait(180)

        self.assertGreater(handle.visual_strength(), resting)
        self.assertEqual(splitter.handleWidth(), 6)

        handle.leaveEvent(QEvent(QEvent.Type.Leave))
        QTest.qWait(180)
        self.assertAlmostEqual(handle.visual_strength(), resting, places=2)
        splitter.close()

    def test_hover_highlights_panel_edges_with_a_soft_center(self) -> None:
        splitter = create_workspace_splitter(
            (QWidget(), QWidget()),
            object_name="HighlightedWorkspaceSplitter",
        )
        palette = splitter.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#171717"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#f2f2f2"))
        splitter.setPalette(palette)
        splitter.resize(800, 400)
        splitter.show()
        self.app.processEvents()
        handle = splitter.handle(1)

        handle.set_visual_strength(0.0)
        self.app.processEvents()
        resting_image = handle.grab().toImage()

        handle.set_visual_strength(0.52)
        self.app.processEvents()
        hover_image = handle.grab().toImage()

        y = handle.height() // 2
        resting_edge = resting_image.pixelColor(0, y).lightness()
        hover_edge = hover_image.pixelColor(0, y).lightness()
        hover_center = hover_image.pixelColor(handle.width() // 2, y).lightness()
        brightness_delta = hover_edge - resting_edge
        self.assertGreaterEqual(brightness_delta, 2)
        self.assertLessEqual(brightness_delta, 16)
        self.assertGreater(hover_edge, hover_center)
        self.assertEqual(
            hover_image.pixelColor(0, 0).lightness(),
            resting_image.pixelColor(0, 0).lightness(),
        )
        splitter.close()

    def test_supports_vertical_and_selectively_collapsible_panels(self) -> None:
        splitter = create_workspace_splitter(
            (QWidget(), QWidget(), QWidget()),
            object_name="TestVerticalWorkspaceSplitter",
            orientation=Qt.Orientation.Vertical,
            collapsible=(True, False, True),
        )

        self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(
            splitter.handle(1).cursor().shape(),
            Qt.CursorShape.SplitVCursor,
        )
        self.assertTrue(splitter.isCollapsible(0))
        self.assertFalse(splitter.isCollapsible(1))
        self.assertTrue(splitter.isCollapsible(2))
        splitter.resize(400, 900)
        splitter.show()
        self.app.processEvents()
        splitter.moveSplitter(0, 1)
        self.app.processEvents()
        self.assertEqual(splitter.sizes()[0], 0)
        self.assertGreater(splitter.sizes()[1], 0)
        splitter.close()

    def test_rejects_panel_configuration_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            create_workspace_splitter(
                (QWidget(), QWidget()),
                object_name="InvalidWorkspaceSplitter",
                sizes=(300,),
            )


if __name__ == "__main__":
    unittest.main()
