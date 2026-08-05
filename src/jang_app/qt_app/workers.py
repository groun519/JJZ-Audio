from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import QThread, Signal

from jang_app.services.job_diagnostics import diagnostic_task


TaskCallable = Callable[[Callable[[int], None]], Any]


class TaskProgressTarget(Protocol):
    def set_running(self, is_running: bool) -> None: ...

    def set_progress(self, value: int) -> None: ...


class TaskWorker(QThread):
    progress_changed = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: TaskCallable) -> None:
        super().__init__()
        self._task = task
        self._diagnostic_task_id = ""

    def set_diagnostic_task_id(self, task_id: str) -> None:
        self._diagnostic_task_id = task_id

    def run(self) -> None:
        with diagnostic_task(self._diagnostic_task_id):
            try:
                self.succeeded.emit(self._task(self.progress_changed.emit))
            except Exception:
                self.failed.emit(traceback.format_exc())
