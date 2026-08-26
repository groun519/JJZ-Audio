from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import QThread, Signal

from jang_app.services.app_logging import get_logger
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
        self._resource_kind = ""
        self._resource_id = ""

    def set_diagnostic_task_id(self, task_id: str) -> None:
        self._diagnostic_task_id = task_id

    def set_resource_owner(self, kind: str, resource_id: str) -> None:
        self._resource_kind = kind.strip()
        self._resource_id = resource_id.strip()

    def owns_resource(self, kind: str, resource_id: str) -> bool:
        return self._resource_kind == kind and self._resource_id == resource_id

    def request_cancel(self) -> None:
        self.requestInterruption()

    def cancel_and_wait(self, timeout_ms: int = 5000) -> bool:
        self.request_cancel()
        if not self.isRunning():
            return True
        return self.wait(max(0, int(timeout_ms)))

    def run(self) -> None:
        with diagnostic_task(self._diagnostic_task_id):
            try:
                self.succeeded.emit(self._task(self.progress_changed.emit))
            except Exception:
                error = traceback.format_exc()
                get_logger().error("Background task failed\n%s", error)
                self.failed.emit(error)
