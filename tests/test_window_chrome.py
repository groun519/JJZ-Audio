from __future__ import annotations

import unittest

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.window_chrome import apply_window_corner_style


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_requests_rounded_corner_preference(self) -> None:
        calls: list[tuple[int, int]] = []
        window = QWidget()

        applied = apply_window_corner_style(
            window,
            rounded=True,
            setter=lambda window_id, preference: calls.append((window_id, preference)) or 0,
        )

        self.assertTrue(applied)
        self.assertEqual(calls, [(int(window.winId()), 2)])
        window.close()

    def test_requests_square_corners_when_maximized(self) -> None:
        calls: list[tuple[int, int]] = []
        window = QWidget()

        applied = apply_window_corner_style(
            window,
            rounded=False,
            setter=lambda window_id, preference: calls.append((window_id, preference)) or 0,
        )

        self.assertTrue(applied)
        self.assertEqual(calls, [(int(window.winId()), 1)])
        window.close()

    def test_dwm_failure_uses_rounded_mask_fallback(self) -> None:
        def fail(window_id: int, preference: int) -> int:
            del window_id, preference
            raise OSError("DWM unavailable")

        window = QWidget()
        window.resize(300, 180)

        self.assertTrue(apply_window_corner_style(window, rounded=True, setter=fail))
        self.assertFalse(window.mask().isEmpty())
        self.assertFalse(window.mask().contains(QPoint(0, 0)))

        self.assertTrue(apply_window_corner_style(window, rounded=False, setter=fail))
        self.assertTrue(window.mask().isEmpty())
        window.close()


if __name__ == "__main__":
    unittest.main()
