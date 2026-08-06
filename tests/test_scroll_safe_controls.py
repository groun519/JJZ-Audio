from __future__ import annotations

import unittest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QScrollArea,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.widgets import ScrollSafeComboBox, ScrollSafeSlider, ScrollSafeSpinBox


class ScrollSafeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_wheel_does_not_change_control_values(self) -> None:
        combo = ScrollSafeComboBox()
        combo.addItems(["first", "second"])
        slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        spin = ScrollSafeSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)

        controls = ((combo, 0), (slider, 50), (spin, 50))
        for control, expected in controls:
            with self.subTest(control=type(control).__name__):
                event = _wheel_event()
                QApplication.sendEvent(control, event)
                value = control.currentIndex() if isinstance(control, ScrollSafeComboBox) else control.value()
                self.assertEqual(value, expected)
                self.assertFalse(event.isAccepted())

    def test_wheel_scrolls_the_parent_instead_of_changing_the_value(self) -> None:
        area = QScrollArea()
        area.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        area.resize(300, 200)
        content = QWidget()
        content.setMinimumHeight(1000)
        layout = QVBoxLayout(content)
        spin = ScrollSafeSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)
        layout.addWidget(spin)
        layout.addStretch(1)
        area.setWidget(content)
        area.show()
        self.app.processEvents()
        scroll_bar = area.verticalScrollBar()
        scroll_bar.setValue(300)

        QApplication.sendEvent(spin, _wheel_event())

        self.assertEqual(spin.value(), 50)
        self.assertGreater(scroll_bar.value(), 300)
        area.close()

    def test_clicking_slider_track_moves_directly_to_pointer(self) -> None:
        slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        slider.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        slider.setRange(0, 100)
        slider.setValue(0)
        slider.resize(240, 30)
        slider.show()
        self.app.processEvents()
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        groove = slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            slider,
        )
        target = groove.center()
        target.setX(round(groove.left() + groove.width() * 0.75))
        moved = QSignalSpy(slider.sliderMoved)

        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=target)

        self.assertGreaterEqual(slider.value(), 70)
        self.assertLessEqual(slider.value(), 80)
        self.assertGreaterEqual(moved.count(), 1)
        slider.close()

    def test_dragging_from_slider_track_continues_to_follow_pointer(self) -> None:
        slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        slider.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        slider.setRange(0, 100)
        slider.setValue(0)
        slider.resize(240, 30)
        slider.show()
        self.app.processEvents()
        start = slider.rect().center()
        end = start + QPoint(80, 0)

        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(slider, end)
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)

        self.assertGreater(slider.value(), 75)
        self.assertFalse(slider.isSliderDown())
        slider.close()


def _wheel_event() -> QWheelEvent:
    return QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


if __name__ == "__main__":
    unittest.main()
