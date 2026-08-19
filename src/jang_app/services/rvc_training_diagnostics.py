from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping
from uuid import uuid4

from jang_app.services.job_diagnostics import (
    current_task_id,
    get_job_diagnostics,
    redact_text,
)
from jang_app.version import __version__


_FIRST_BATCH_MARKER = "JJZERO_TRAINING_FIRST_BATCH_READY"
_LOADER_START_MARKER = "JJZERO_TRAINING_DATA_LOADER_START"
_LOADER_TIMEOUT_MARKERS = (
    "dataloader timed out",
    "data loader timed out",
)
_NATIVE_CRASH_MARKERS = (
    "windows fatal exception: access violation",
    "0xc0000005",
    "3221225477",
    "rtluserthreadstart",
)


@dataclass(frozen=True)
class RvcTrainingAttempt:
    attempt_id: str
    ordinal: int
    folder: Path
    started_at: str


@dataclass(frozen=True)
class RvcTrainingProcessStatus:
    pid: int
    process_name: str
    role: str
    alive: bool
    exit_code: int | None


class RvcTrainingDiagnostics:
    """Records one training task without coupling the RVC runtime to the app."""

    def __init__(self, root: Path, task_id: str, model_id: str) -> None:
        self.root = Path(root) / "training"
        self.task_id = task_id
        self.model_id = model_id
        self._lock = threading.RLock()
        self._attempt_count = 0
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_json(
            self.root / "manifest.json",
            {
                "schema_version": 1,
                "app_version": __version__,
                "task_id": task_id,
                "model_id": model_id,
                "created_at": _iso_now(),
            },
        )

    @classmethod
    def for_current_task(
        cls,
        model_id: str,
    ) -> RvcTrainingDiagnostics | None:
        task_id = current_task_id()
        if not task_id or task_id == "-":
            return None
        diagnostics = get_job_diagnostics()
        task_root = diagnostics.job_path(task_id)
        if not task_root.is_dir():
            return None
        try:
            return cls(task_root, task_id, model_id)
        except OSError:
            return None

    def begin_attempt(self, metadata: Mapping[str, object]) -> RvcTrainingAttempt:
        with self._lock:
            self._attempt_count += 1
            ordinal = self._attempt_count
            attempt_id = f"a{ordinal}-{uuid4().hex[:8]}"
            folder = self.root / "attempts" / attempt_id
            (folder / "processes").mkdir(parents=True, exist_ok=True)
            started_at = _iso_now()
            payload = {
                "schema_version": 1,
                "task_id": self.task_id,
                "attempt_id": attempt_id,
                "ordinal": ordinal,
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "diagnostic_code": "",
                "metadata": _json_values(metadata),
            }
            self._write_json(folder / "attempt.json", payload)
            self.event(
                "attempt_started",
                attempt_id=attempt_id,
                ordinal=ordinal,
                metadata=metadata,
            )
            return RvcTrainingAttempt(attempt_id, ordinal, folder, started_at)

    def event(self, event: str, **data: object) -> None:
        payload = {
            "timestamp": _iso_now(),
            "monotonic_seconds": round(monotonic(), 6),
            "task_id": self.task_id,
            "event": event,
            **_json_values(data),
        }
        try:
            with self._lock:
                with (self.root / "events.jsonl").open(
                    "a",
                    encoding="utf-8",
                ) as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                    stream.write("\n")
        except OSError:
            return

    def finish_attempt(
        self,
        attempt: RvcTrainingAttempt,
        *,
        status: str,
        returncode: int | None,
        diagnostic_code: str = "",
        detail: str = "",
    ) -> None:
        path = attempt.folder / "attempt.json"
        payload = _read_json(path)
        payload.update(
            status=status,
            returncode=returncode,
            finished_at=_iso_now(),
            diagnostic_code=diagnostic_code,
            detail=redact_text(detail),
        )
        self._write_json(path, payload)
        self.event(
            "attempt_finished",
            attempt_id=attempt.attempt_id,
            status=status,
            returncode=returncode,
            diagnostic_code=diagnostic_code,
            detail=detail,
        )

    def capture_train_log(
        self,
        attempt: RvcTrainingAttempt,
        source: Path,
        offset: int,
    ) -> None:
        if not source.is_file():
            return
        try:
            with source.open("rb") as stream:
                stream.seek(max(0, int(offset)))
                content = stream.read()
            (attempt.folder / "train.log").write_bytes(content)
        except OSError:
            return

    def record_runtime(self, metadata: Mapping[str, object]) -> None:
        self._write_json(self.root / "runtime.json", _json_values(metadata))

    def diagnose_attempt(
        self,
        attempt: RvcTrainingAttempt,
        output: str,
    ) -> str:
        lowered = output.casefold()
        if any(marker in lowered for marker in _LOADER_TIMEOUT_MARKERS):
            return "RVC_FIRST_BATCH_TIMEOUT"
        process_text = _read_process_diagnostics(attempt.folder / "processes")
        process_lowered = process_text.casefold()
        if any(
            marker in lowered or marker in process_lowered
            for marker in _NATIVE_CRASH_MARKERS
        ):
            return "RVC_NATIVE_RUNTIME_CRASH"
        if "data_loader_exception" in process_lowered:
            if "modulenotfounderror" in process_lowered or "importerror" in process_lowered:
                return "RVC_WORKER_IMPORT_FAILED"
            return "RVC_WORKER_EXITED"
        if "uncaught_exception" in process_lowered:
            if "modulenotfounderror" in process_lowered or "importerror" in process_lowered:
                return "RVC_WORKER_IMPORT_FAILED"
            return "RVC_WORKER_BOOT_FAILED"
        if _LOADER_START_MARKER.casefold() in lowered and _FIRST_BATCH_MARKER.casefold() not in lowered:
            return "RVC_FIRST_BATCH_TIMEOUT"
        return ""

    def _write_json(self, path: Path, value: Mapping[str, object]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError:
            return


class RvcTrainingAttemptMonitor:
    def __init__(
        self,
        diagnostics: RvcTrainingDiagnostics | None,
        attempt: RvcTrainingAttempt | None,
        *,
        activity_callback: Callable[[str], None] | None = None,
        interval_seconds: float = 15.0,
    ) -> None:
        self._diagnostics = diagnostics
        self._attempt = attempt
        self._activity_callback = activity_callback
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._started_at = monotonic()
        self._last_output_at = self._started_at
        self._loader_started_at = 0.0
        self._first_batch_ready_at = 0.0
        self._reported_dead_workers: set[int] = set()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._diagnostics is None or self._attempt is None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="RvcTrainingDiagnostics",
            daemon=True,
        )
        self._thread.start()

    def observe_output(self, line: str) -> None:
        now = monotonic()
        text = str(line).strip()
        with self._lock:
            self._last_output_at = now
            if _LOADER_START_MARKER in text and self._loader_started_at <= 0:
                self._loader_started_at = now
                self._event("first_batch_wait_started")
            if _FIRST_BATCH_MARKER in text and self._first_batch_ready_at <= 0:
                self._first_batch_ready_at = now
                self._event(
                    "first_batch_ready",
                    duration_seconds=round(max(0.0, now - self._loader_started_at), 3),
                )

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            with self._lock:
                elapsed = monotonic() - self._started_at
                idle = monotonic() - self._last_output_at
                waiting = self._loader_started_at > 0 and self._first_batch_ready_at <= 0
                waiting_seconds = (
                    monotonic() - self._loader_started_at if waiting else 0.0
                )
            statuses = self._process_statuses()
            workers = tuple(status for status in statuses if status.role == "worker")
            alive = sum(status.alive for status in workers)
            self._event(
                "watchdog_heartbeat",
                elapsed_seconds=round(elapsed, 3),
                output_idle_seconds=round(idle, 3),
                waiting_for_first_batch=waiting,
                first_batch_wait_seconds=round(waiting_seconds, 3),
                process_count=len(statuses),
                alive_processes=sum(status.alive for status in statuses),
                worker_count=len(workers),
                alive_workers=alive,
                processes=[asdict(status) for status in statuses],
            )
            if waiting and self._activity_callback is not None:
                self._activity_callback(
                    "JJZERO_TRAINING_FIRST_BATCH_WAIT "
                    f"elapsed={round(waiting_seconds)} "
                    f"workers_alive={alive} workers_seen={len(workers)}"
                )
            self._report_dead_workers(workers)

    def _report_dead_workers(
        self,
        workers: tuple[RvcTrainingProcessStatus, ...],
    ) -> None:
        if self._activity_callback is None:
            return
        for worker in workers:
            if worker.alive or worker.pid in self._reported_dead_workers:
                continue
            self._reported_dead_workers.add(worker.pid)
            self._event(
                "data_worker_exited",
                pid=worker.pid,
                exit_code=worker.exit_code,
            )
            self._activity_callback(
                "JJZERO_DATA_LOADER_WORKER_EXITED "
                f"pid={worker.pid} exit_code={worker.exit_code}"
            )

    def _process_statuses(self) -> tuple[RvcTrainingProcessStatus, ...]:
        if self._attempt is None:
            return ()
        statuses: list[RvcTrainingProcessStatus] = []
        for path in sorted((self._attempt.folder / "processes").glob("*.jsonl")):
            try:
                pid = int(path.stem)
            except ValueError:
                continue
            process_name = _process_name(path)
            role = "parent" if process_name == "MainProcess" else "worker"
            alive, exit_code = _process_status(pid)
            statuses.append(
                RvcTrainingProcessStatus(
                    pid,
                    process_name,
                    role,
                    alive,
                    exit_code,
                )
            )
        return tuple(statuses)

    def _event(self, event: str, **data: object) -> None:
        if self._diagnostics is None or self._attempt is None:
            return
        self._diagnostics.event(
            event,
            attempt_id=self._attempt.attempt_id,
            **data,
        )


def _process_status(pid: int) -> tuple[bool, int | None]:
    if os.name == "nt":
        try:
            import ctypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return False, None
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(
                    process,
                    ctypes.byref(exit_code),
                ):
                    return False, None
                value = int(exit_code.value)
                return value == 259, None if value == 259 else value
            finally:
                ctypes.windll.kernel32.CloseHandle(process)
        except (AttributeError, OSError):
            return False, None
    try:
        os.kill(pid, 0)
    except OSError:
        return False, None
    return True, None


def _read_process_diagnostics(folder: Path) -> str:
    parts: list[str] = []
    for path in sorted(folder.glob("*")):
        if not path.is_file() or path.suffix not in {".jsonl", ".log"}:
            continue
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _process_name(path: Path) -> str:
    try:
        first_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        payload = json.loads(first_line)
    except (OSError, ValueError, TypeError, IndexError):
        return "unknown"
    return str(payload.get("process_name") or "unknown") if isinstance(payload, dict) else "unknown"


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_values(value: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): _json_value(item)
        for key, item in value.items()
    }


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return _redact_path(value)
    if isinstance(value, Mapping):
        return _json_values(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return redact_text(value)


def _redact_path(path: Path) -> str:
    value = str(path)
    try:
        home = str(Path.home())
        if value.casefold().startswith(home.casefold()):
            value = "<USER_HOME>" + value[len(home) :]
    except RuntimeError:
        pass
    return redact_text(value)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
