from __future__ import annotations

import unittest

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent
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

    def test_supports_vertical_and_selectively_collapsible_panels(self) -> None:
        splitter = create_workspace_splitter(
            (QWidget(), QWidget(), QWidget()),
            object_name="TestVerticalWorkspaceSplitter",
            orientation=Qt.Orientation.Vertical,
            collapsible=(True, False, True),
        )

        self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
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
