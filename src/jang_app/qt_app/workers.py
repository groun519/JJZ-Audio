from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import QThread, Signal


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

    def run(self) -> None:
        try:
            self.succeeded.emit(self._task(self.progress_changed.emit))
        except Exception:
            self.failed.emit(traceback.format_exc())
