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
        self.history_refreshes = 0

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

    def refresh_history(self) -> None:
        self.history_refreshes += 1


class ProcessingQueueDrawerTests(unittest.TestCase):
    def test_opening_activity_popover_refreshes_persisted_history(self) -> None:
        panel = _VisibilityTarget()
        button = _VisibilityTarget()
        positions: list[bool] = []
        window = SimpleNamespace(
            processing_queue_panel=panel,
            processing_queue_button=button,
            _processing_queue_drawer_open=False,
            _position_processing_queue=lambda: positions.append(True),
        )

        MainWindow._open_processing_queue_drawer(window)

        self.assertTrue(window._processing_queue_drawer_open)
        self.assertTrue(panel.visible)
        self.assertTrue(button.checked)
        self.assertEqual(panel.history_refreshes, 1)
        self.assertEqual(positions, [True])

    def test_queue_drawer_opens_without_tasks(self) -> None:
        panel = _VisibilityTarget(has_tasks=False)
        button = _VisibilityTarget()
        positions: list[bool] = []
        window = SimpleNamespace(
            processing_queue_panel=panel,
            processing_queue_button=button,
            _processing_queue_drawer_open=False,
            _position_processing_queue=lambda: positions.append(True),
        )

        MainWindow._open_processing_queue_drawer(window)

        self.assertTrue(window._processing_queue_drawer_open)
        self.assertTrue(panel.visible)
        self.assertTrue(button.checked)
        self.assertEqual(positions, [True])

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

    def test_activity_job_opens_the_diagnostics_window(self) -> None:
        window = SimpleNamespace(
            toast_stack=SimpleNamespace(dismiss_all=lambda: dismissed.append(True)),
            diagnostics_window=SimpleNamespace(
                show_diagnostics=lambda task_id: selected.append(task_id)
            ),
            _close_processing_queue_drawer=lambda: closed.append(True),
        )
        dismissed: list[bool] = []
        closed: list[bool] = []
        selected: list[str] = []

        MainWindow._open_diagnostics_window(window, "task-1")

        self.assertEqual(selected, ["task-1"])
        self.assertEqual((dismissed, closed), ([True], [True]))

    def test_close_diagnostics_closes_the_window(self) -> None:
        closed: list[bool] = []
        window = SimpleNamespace(
            diagnostics_window=SimpleNamespace(close=lambda: closed.append(True)),
        )

        MainWindow._close_diagnostics_window(window)

        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
