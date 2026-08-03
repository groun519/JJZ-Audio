from __future__ import annotations

import unittest

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSizePolicy

from jang_app.qt_app.overflow_title_label import OverflowTitleLabel


class OverflowTitleLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_long_title_uses_ignored_width_and_hover_marquee(self) -> None:
        label = OverflowTitleLabel("A long title that cannot fit inside this compact row")
        label.resize(120, 22)
        label.show()
        self.app.processEvents()

        point = QPointF(1, 1)
        label.enterEvent(QEnterEvent(point, point, point))
        QTest.qWait(500)

        self.assertEqual(label.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.assertGreater(label.get_scroll_offset(), 0)
        self.assertEqual(label.toolTip(), label.text())
        label.leaveEvent(QEvent(QEvent.Type.Leave))
        QTest.qWait(220)
        self.assertAlmostEqual(label.get_scroll_offset(), 0, delta=1)
        label.close()


if __name__ == "__main__":
    unittest.main()
