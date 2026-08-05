from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from jang_app.services.job_diagnostics import JobDiagnostics, classify_error


TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"
FINISHED_TASK_STATES = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}


@dataclass(frozen=True)
class ProcessingTask:
    task_id: str
    title: str
    detail: str
    status: str
    progress: int
    created_at: datetime
    finished_at: datetime | None = None
    error: str = ""
    diagnostic_path: Path | None = None
    diagnostic_code: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == TASK_RUNNING

    @property
    def is_finished(self) -> bool:
        return self.status in FINISHED_TASK_STATES


QueueListener = Callable[[tuple[ProcessingTask, ...]], None]


class ProcessingQueue:
    def __init__(self, history_limit: int = 24, diagnostics: JobDiagnostics | None = None) -> None:
        self._history_limit = max(1, history_limit)
        self._diagnostics = diagnostics
        self._tasks: list[ProcessingTask] = []
        self._listeners: list[QueueListener] = []
        self._lock = RLock()

    @property
    def diagnostics(self) -> JobDiagnostics | None:
        return self._diagnostics

    def tasks(self) -> tuple[ProcessingTask, ...]:
        with self._lock:
            return tuple(self._tasks)

    def active_count(self) -> int:
        return sum(task.is_active for task in self.tasks())

    def subscribe(self, listener: QueueListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)
        listener(self.tasks())

    def unsubscribe(self, listener: QueueListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def start(self, title: str, detail: str = "", progress: int = 0) -> str:
        task_id = uuid4().hex
        diagnostic_path = (
            self._diagnostics.start_job(task_id, title, detail) if self._diagnostics is not None else None
        )
        task = ProcessingTask(
            task_id=task_id,
            title=title.strip() or "Processing",
            detail=detail.strip(),
            status=TASK_RUNNING,
            progress=_clamp_progress(progress),
            created_at=datetime.now(UTC),
            diagnostic_path=diagnostic_path,
        )
        with self._lock:
            self._tasks.insert(0, task)
            self._prune_history()
        if self._diagnostics is not None and task.progress:
            self._diagnostics.update_progress(task_id, task.progress)
        self._notify()
        return task.task_id

    def update_progress(self, task_id: str, progress: int) -> None:
        value = _clamp_progress(progress)
        did_update = self._update_task(task_id, lambda task: replace(task, progress=value))
        if did_update and self._diagnostics is not None:
            self._diagnostics.update_progress(task_id, value)

    def update_detail(self, task_id: str, detail: str) -> None:
        did_update = self._update_task(task_id, lambda task: replace(task, detail=detail.strip()))
        if did_update and self._diagnostics is not None:
            self._diagnostics.update_detail(task_id, detail)

    def complete(self, task_id: str) -> None:
        did_update = self._update_task(
            task_id,
            lambda task: replace(
                task,
                status=TASK_COMPLETED,
                progress=100,
                finished_at=datetime.now(UTC),
                error="",
            ),
        )
        if did_update and self._diagnostics is not None:
            self._diagnostics.complete_job(task_id)

    def fail(self, task_id: str, error: str) -> None:
        classification = classify_error(error)
        did_update = self._update_task(
            task_id,
            lambda task: replace(
                task,
                status=TASK_FAILED,
                finished_at=datetime.now(UTC),
                error=error.strip(),
                diagnostic_code=classification.code,
            ),
        )
        if did_update and self._diagnostics is not None:
            self._diagnostics.fail_job(task_id, error)

    def cancel(self, task_id: str, detail: str = "Stopped") -> None:
        did_update = self._update_task(
            task_id,
            lambda task: replace(
                task,
                detail=detail.strip(),
                status=TASK_CANCELLED,
                finished_at=datetime.now(UTC),
                error="",
            ),
        )
        if did_update and self._diagnostics is not None:
            self._diagnostics.cancel_job(task_id)

    def clear_finished(self) -> None:
        with self._lock:
            self._tasks = [task for task in self._tasks if not task.is_finished]
        self._notify()

    def _update_task(self, task_id: str, update: Callable[[ProcessingTask], ProcessingTask]) -> bool:
        did_update = False
        with self._lock:
            for index, task in enumerate(self._tasks):
                if task.task_id != task_id or task.is_finished:
                    continue
                self._tasks[index] = update(task)
                did_update = True
                break
        if did_update:
            self._notify()
        return did_update

    def _prune_history(self) -> None:
        finished_indexes = [index for index, task in enumerate(self._tasks) if task.is_finished]
        while len(self._tasks) > self._history_limit and finished_indexes:
            self._tasks.pop(finished_indexes.pop())
            finished_indexes = [index for index, task in enumerate(self._tasks) if task.is_finished]

    def _notify(self) -> None:
        tasks = self.tasks()
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(tasks)


def _clamp_progress(progress: int) -> int:
    return max(0, min(100, int(progress)))
