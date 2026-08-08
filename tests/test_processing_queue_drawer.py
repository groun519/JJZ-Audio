from __future__ import annotations

import unittest
from types import SimpleNamespace

from jang_app.qt_app.main_window import MainWindow


class _VisibilityTarget:
    def __init__(self, *, visible: bool = False, has_tasks: bool = True) -> None:
        self.visible = visible
        self.checked = False
        self.has_tasks_value = has_tasks
        self.language_updates = 0

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def has_tasks(self) -> bool:
        return self.has_tasks_value

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        self.checked = checked

    def apply_language(self) -> None:
        self.language_updates += 1


class ProcessingQueueDrawerTests(unittest.TestCase):
    def test_opening_queue_drawer_closes_log_drawer(self) -> None:
        panel = _VisibilityTarget()
        button = _VisibilityTarget()
        log_drawer = _VisibilityTarget(visible=True)
        positions: list[bool] = []
        window = SimpleNamespace(
            processing_queue_panel=panel,
            processing_queue_button=button,
            log_drawer=log_drawer,
            _processing_queue_drawer_open=False,
            _position_processing_queue=lambda: positions.append(True),
        )

        MainWindow._open_processing_queue_drawer(window)

        self.assertTrue(window._processing_queue_drawer_open)
        self.assertTrue(panel.visible)
        self.assertTrue(button.checked)
        self.assertFalse(log_drawer.visible)
        self.assertEqual(positions, [True])

    def test_queue_drawer_does_not_open_without_tasks(self) -> None:
        panel = _VisibilityTarget(has_tasks=False)
        button = _VisibilityTarget()
        window = SimpleNamespace(
            processing_queue_panel=panel,
            processing_queue_button=button,
            log_drawer=_VisibilityTarget(),
            _processing_queue_drawer_open=False,
            _position_processing_queue=lambda: self.fail("empty drawer was positioned"),
        )

        MainWindow._open_processing_queue_drawer(window)

        self.assertFalse(window._processing_queue_drawer_open)
        self.assertFalse(panel.visible)
        self.assertFalse(button.checked)

    def test_closing_queue_drawer_hides_panel(self) -> None:
        panel = _VisibilityTarget(visible=True)
        button = _VisibilityTarget()
        button.checked = True
        positions: list[bool] = []
        window = SimpleNamespace(
            processing_queue_panel=panel,
            processing_queue_button=button,
            _processing_queue_drawer_open=True,
            _position_processing_queue=lambda: positions.append(True),
        )

        MainWindow._close_processing_queue_drawer(window)

        self.assertFalse(window._processing_queue_drawer_open)
        self.assertFalse(panel.visible)
        self.assertFalse(button.checked)
        self.assertEqual(positions, [True])


if __name__ == "__main__":
    unittest.main()
