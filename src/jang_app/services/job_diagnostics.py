from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from jang_app.config import LOG_DIR
from jang_app.services.text_tail import text_tail
from jang_app.version import __version__


SESSION_ID = uuid4().hex[:12]
_CURRENT_TASK_ID: ContextVar[str] = ContextVar("diagnostic_task_id", default="-")
_SENSITIVE_OPTION = re.compile(r"(?:token|password|passwd|cookie|secret|authorization|api[-_]?key)", re.I)
_URL = re.compile(r"https?://[^\s'\"<>]+", re.I)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(token|password|passwd|cookie|secret|authorization|api[-_]?key)\s*([=:])\s*([^\s,;]+)"
)


@dataclass(frozen=True)
class ErrorClassification:
    code: str
    summary: str


def current_task_id() -> str:
    return _CURRENT_TASK_ID.get()


@contextmanager
def diagnostic_task(task_id: str) -> Iterator[None]:
    token = _CURRENT_TASK_ID.set(task_id or "-")
    try:
        yield
    finally:
        _CURRENT_TASK_ID.reset(token)


def classify_error(error: str) -> ErrorClassification:
    value = error.lower()
    rules = (
        (("3221225620", "0xc0000094", "integer division by zero"), "RVC_CPU_RUNTIME_INCOMPATIBLE", "RVC runtime crashed on the selected CPU path."),
        (("cuda out of memory", "cublas_status_alloc_failed"), "CUDA_OUT_OF_MEMORY", "The GPU did not have enough free memory."),
        (("no kernel image is available", "not compatible with the current pytorch", "cuda architecture sm_120", "requires torch 2.7.1+cu128"), "CUDA_ARCHITECTURE_UNSUPPORTED", "The bundled RVC runtime does not support this GPU architecture."),
        (("cuda is not available", "no cuda gpus are available", "invalid device ordinal"), "CUDA_UNAVAILABLE", "The selected CUDA device is unavailable."),
        (("torch_directml", "privateuseone", "directml device"), "DIRECTML_RUNTIME_FAILED", "The DirectML runtime or selected DirectML device failed."),
        (("rocm", "hip error", "hip runtime"), "ROCM_RUNTIME_FAILED", "The AMD ROCm runtime or selected AMD GPU failed."),
        (("no space left on device", "not enough space on the disk", "disk full"), "STORAGE_INSUFFICIENT", "The storage device does not have enough free space."),
        (("ffmpeg is not available", "ffmpeg was not found", "no such file or directory: 'ffmpeg'"), "FFMPEG_UNAVAILABLE", "FFmpeg is unavailable."),
        (("modulenotfounderror", "no module named"), "PYTHON_MODULE_MISSING", "A required Python module is unavailable."),
        (("connectionerror", "urlerror", "timed out", "failed to download", "http error"), "NETWORK_DOWNLOAD_FAILED", "A network download failed."),
        (("filename or extension is too long", "the filename, directory name, or volume label syntax is incorrect"), "INVALID_MEDIA_PATH", "A media file path is invalid or too long."),
        (("cancelled", "canceled", "stopped by user"), "CANCELLED", "The operation was stopped."),
    )
    for needles, code, summary in rules:
        if any(needle in value for needle in needles):
            return ErrorClassification(code, summary)
    return ErrorClassification("UNEXPECTED_ERROR", "The operation failed unexpectedly.")


def redact_text(value: object) -> str:
    text = str(value)
    text = _URL.sub(lambda match: _redact_url(match.group(0)), text)
    text = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)
    return text


def redact_command(args: Sequence[object]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for raw in args:
        value = str(raw)
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        option, separator, option_value = value.partition("=")
        if value.startswith("-") and _SENSITIVE_OPTION.search(option):
            redacted.append(f"{option}=<redacted>" if separator else option)
            hide_next = not separator
            continue
        if value.lower() == "bearer":
            redacted.append(value)
            hide_next = True
            continue
        redacted.append(redact_text(value))
    return redacted


class JobDiagnostics:
    def __init__(
        self,
        root: Path,
        *,
        session_id: str = SESSION_ID,
        success_retention_days: int = 14,
        failure_retention_days: int = 30,
        max_jobs: int = 50,
    ) -> None:
        self.root = Path(root)
        self.session_id = session_id
        self._success_retention = timedelta(days=max(1, success_retention_days))
        self._failure_retention = timedelta(days=max(1, failure_retention_days))
        self._max_jobs = max(1, max_jobs)
        self._summaries: dict[str, dict[str, object]] = {}
        self._lock = RLock()
        self._prepare_root()

    def start_job(
        self,
        task_id: str,
        title: str,
        detail: str = "",
        metadata: dict[str, object] | None = None,
    ) -> Path | None:
        now = _iso_now()
        summary: dict[str, object] = {
            "schema_version": 1,
            "session_id": self.session_id,
            "task_id": task_id,
            "app_version": __version__,
            "title": redact_text(title),
            "detail": redact_text(detail),
            "status": "running",
            "progress": 0,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "diagnostic_code": "",
            "diagnostic_summary": "",
            "error": "",
            "environment": _environment_summary(),
            "metadata": _sanitize_json(metadata or {}),
        }
        try:
            with self._lock:
                path = self.job_path(task_id)
                path.mkdir(parents=True, exist_ok=True)
                self._summaries[task_id] = summary
                self._write_summary(task_id)
                self._append_event(task_id, "job_started", title=title, detail=detail)
            return path
        except OSError:
            return None

    def update_progress(self, task_id: str, progress: int) -> None:
        self._update(task_id, progress=max(0, min(100, int(progress))))
        self.event(task_id, "progress", progress=max(0, min(100, int(progress))))

    def update_detail(self, task_id: str, detail: str) -> None:
        self._update(task_id, detail=redact_text(detail))
        self.event(task_id, "detail", detail=detail)

    def complete_job(self, task_id: str) -> None:
        self._finish(task_id, "completed", progress=100)

    def fail_job(self, task_id: str, error: str) -> ErrorClassification:
        classification = classify_error(error)
        self._finish(
            task_id,
            "failed",
            diagnostic_code=classification.code,
            diagnostic_summary=classification.summary,
            error=redact_text(error),
        )
        return classification

    def cancel_job(self, task_id: str) -> None:
        self._finish(
            task_id,
            "cancelled",
            diagnostic_code="CANCELLED",
            diagnostic_summary="The operation was stopped.",
        )

    def event(self, task_id: str, event: str, **data: object) -> None:
        try:
            with self._lock:
                self._append_event(task_id, event, **data)
        except OSError:
            return

    def start_command(self, task_id: str, args: Sequence[object], cwd: Path | None) -> str:
        command_id = uuid4().hex[:10]
        command = redact_command(args)
        self.event(
            task_id,
            "command_started",
            command_id=command_id,
            command=command,
            cwd=str(cwd) if cwd else "",
        )
        self.append_command_output(task_id, f"\n[{_iso_now()}] $ {' '.join(command)}\n")
        return command_id

    def append_command_output(self, task_id: str, output: str) -> None:
        try:
            with self._lock:
                path = self.job_path(task_id)
                if not path.is_dir():
                    return
                with (path / "command.log").open("a", encoding="utf-8", errors="replace") as stream:
                    stream.write(redact_text(output))
                    if output and not output.endswith(("\n", "\r")):
                        stream.write("\n")
        except OSError:
            return

    def finish_command(
        self,
        task_id: str,
        command_id: str,
        *,
        returncode: int | None,
        duration_seconds: float,
        cancelled: bool = False,
        error: str = "",
    ) -> None:
        self.event(
            task_id,
            "command_finished",
            command_id=command_id,
            returncode=returncode,
            duration_seconds=round(max(0.0, duration_seconds), 3),
            cancelled=cancelled,
            error=error,
        )

    def job_path(self, task_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", task_id) or "unknown"
        return self.root / safe_id

    def build_report(self, task_id: str, error_tail_lines: int = 40) -> str:
        summary = self._load_summary(task_id)
        if not summary:
            return "Diagnostics unavailable."
        environment = summary.get("environment") if isinstance(summary.get("environment"), dict) else {}
        error = str(summary.get("error") or "")
        error_tail = "\n".join(error.splitlines()[-max(1, error_tail_lines):])
        command_tail = _read_text_tail(
            self.job_path(task_id) / "command.log",
            max_lines=error_tail_lines,
        )
        lines = [
            "JJZero Audio diagnostics",
            f"App: {summary.get('app_version', '')}",
            f"Session ID: {summary.get('session_id', '')}",
            f"Task ID: {summary.get('task_id', task_id)}",
            f"Status: {summary.get('status', '')}",
            f"Diagnostic ID: {summary.get('diagnostic_code') or 'NONE'}",
            f"Started: {summary.get('started_at', '')}",
            f"Finished: {summary.get('finished_at') or ''}",
            f"OS: {environment.get('platform', '')}",
            f"Python: {environment.get('python', '')}",
            f"Frozen: {environment.get('frozen', False)}",
            f"RVC backend: {environment.get('rvc_backend', '')}",
            f"RVC adapter: {environment.get('rvc_adapter', '')}",
            f"RVC desired profile: {environment.get('rvc_desired_profile', '')}",
            f"RVC installed profile: {environment.get('rvc_installed_profile', '')}",
            f"RVC profile version: {environment.get('rvc_profile_version', '')}",
            f"RVC preferred profile: {environment.get('rvc_preferred_profile', '')}",
            f"RVC preferred version: {environment.get('rvc_preferred_version', '')}",
            f"RVC activation: {environment.get('rvc_activation_status', '')}",
            f"RVC activation detail: {environment.get('rvc_activation_detail', '')}",
            f"RVC failed fallback: {environment.get('rvc_failed_fallback_profile', '')}",
            f"RVC failed fallback version: {environment.get('rvc_failed_fallback_version', '')}",
            f"Detail: {summary.get('detail', '')}",
            f"Log folder: {self.job_path(task_id)}",
        ]
        if error_tail:
            lines.extend(("", "Error tail:", error_tail))
        if command_tail:
            lines.extend(("", "Command output tail:", command_tail))
        return "\n".join(lines)

    def _prepare_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._recover_interrupted_jobs()
            self._prune()
        except OSError:
            return

    def _recover_interrupted_jobs(self) -> None:
        for path in self.root.iterdir():
            summary = _read_json(path / "summary.json") if path.is_dir() else None
            if not summary or summary.get("status") != "running":
                continue
            summary.update(
                status="failed",
                finished_at=_iso_now(),
                updated_at=_iso_now(),
                diagnostic_code="APP_INTERRUPTED",
                diagnostic_summary="The application stopped before the job finished.",
            )
            _write_json(path / "summary.json", summary)

    def _prune(self) -> None:
        now = datetime.now(UTC)
        retained: list[tuple[datetime, Path]] = []
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            summary = _read_json(path / "summary.json") or {}
            timestamp = _parse_time(summary.get("finished_at") or summary.get("updated_at"))
            age = now - timestamp
            failed = summary.get("status") == "failed"
            retention = self._failure_retention if failed else self._success_retention
            if age > retention:
                shutil.rmtree(path, ignore_errors=True)
            else:
                retained.append((timestamp, path))
        for _timestamp, path in sorted(retained, reverse=True)[self._max_jobs :]:
            shutil.rmtree(path, ignore_errors=True)

    def _update(self, task_id: str, **values: object) -> None:
        try:
            with self._lock:
                summary = self._summaries.get(task_id) or self._load_summary(task_id)
                if not summary:
                    return
                summary.update(values)
                summary["updated_at"] = _iso_now()
                self._summaries[task_id] = summary
                self._write_summary(task_id)
        except OSError:
            return

    def _finish(self, task_id: str, status: str, **values: object) -> None:
        now = _iso_now()
        self._update(task_id, status=status, finished_at=now, **values)
        self.event(task_id, "job_finished", status=status, **values)

    def _load_summary(self, task_id: str) -> dict[str, object] | None:
        cached = self._summaries.get(task_id)
        if cached is not None:
            return dict(cached)
        return _read_json(self.job_path(task_id) / "summary.json")

    def _write_summary(self, task_id: str) -> None:
        summary = self._summaries.get(task_id)
        if summary is not None:
            _write_json(self.job_path(task_id) / "summary.json", summary)

    def _append_event(self, task_id: str, event: str, **data: object) -> None:
        path = self.job_path(task_id)
        if not path.is_dir():
            return
        payload = {
            "timestamp": _iso_now(),
            "session_id": self.session_id,
            "task_id": task_id,
            "event": event,
            **_sanitize_json(data),
        }
        with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


_diagnostics: JobDiagnostics | None = None
_diagnostics_lock = RLock()


def get_job_diagnostics() -> JobDiagnostics:
    global _diagnostics
    with _diagnostics_lock:
        if _diagnostics is None:
            _diagnostics = JobDiagnostics(LOG_DIR / "jobs")
        return _diagnostics


def _environment_summary() -> dict[str, object]:
    summary: dict[str, object] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": str(Path(sys.executable)),
        "pid": os.getpid(),
    }
    try:
        from jang_app.config import APP_PATHS
        from jang_app.services.runtime_installation import installed_rvc_runtime_profile
        from jang_app.services.rvc_runtime_profile import detect_rvc_hardware

        hardware = detect_rvc_hardware()
        installed = installed_rvc_runtime_profile(APP_PATHS.runtime_root / "rvc")
        summary.update(
            rvc_backend=hardware.backend.value,
            rvc_adapter=hardware.adapter.name if hardware.adapter is not None else "CPU",
            rvc_desired_profile=hardware.profile,
            rvc_installed_profile=installed.profile if installed is not None else "",
            rvc_profile_version=installed.version if installed is not None else "",
            rvc_preferred_profile=installed.preferred_profile if installed is not None else "",
            rvc_preferred_version=installed.preferred_version if installed is not None else "",
            rvc_activation_status=installed.activation_status if installed is not None else "",
            rvc_activation_detail=installed.validation_detail if installed is not None else "",
            rvc_failed_fallback_profile=(
                installed.failed_fallback_profile if installed is not None else ""
            ),
            rvc_failed_fallback_version=(
                installed.failed_fallback_version if installed is not None else ""
            ),
        )
    except Exception:
        summary.update(
            rvc_backend="unknown",
            rvc_adapter="unknown",
            rvc_desired_profile="",
            rvc_installed_profile="",
            rvc_profile_version="",
            rvc_preferred_profile="",
            rvc_preferred_version="",
            rvc_activation_status="",
            rvc_activation_detail="",
            rvc_failed_fallback_profile="",
            rvc_failed_fallback_version="",
        )
    return summary


def _sanitize_json(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(value)


def _read_text_tail(path: Path, *, max_lines: int) -> str:
    try:
        return text_tail(path.read_text(encoding="utf-8", errors="replace"), max_lines=max_lines)
    except OSError:
        return ""


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))
    except ValueError:
        return "<redacted-url>"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, UTC)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
