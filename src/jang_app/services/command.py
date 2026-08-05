from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Mapping, Sequence

from jang_app.services.app_logging import get_logger
from jang_app.services.job_diagnostics import (
    JobDiagnostics,
    current_task_id,
    get_job_diagnostics,
    redact_command,
)


@dataclass(frozen=True)
class CommandResult:
    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool = False

    @property
    def output(self) -> str:
        return (self.stderr or self.stdout).strip()


class CommandCancellation:
    def __init__(self) -> None:
        self._lock = RLock()
        self._requested = False
        self._process: subprocess.Popen[str] | None = None

    @property
    def is_requested(self) -> bool:
        with self._lock:
            return self._requested

    def request_cancel(self) -> None:
        with self._lock:
            self._requested = True
            process = self._process
        if process is not None:
            _terminate_process_tree(process)

    def _attach(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = process
            should_cancel = self._requested
        if should_cancel:
            _terminate_process_tree(process)

    def _detach(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._process is process:
                self._process = None


def run_command(
    args: Sequence[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    output_callback: Callable[[str], None] | None = None,
    *,
    diagnostics: JobDiagnostics | None = None,
) -> CommandResult:
    logger = get_logger()
    logger.info("Running command: %s", " ".join(redact_command(args)))
    task_id, recorder, command_id, started = _start_diagnostic_command(args, cwd, diagnostics)
    callback = _diagnostic_output_callback(task_id, recorder, output_callback)
    try:
        if output_callback is not None:
            result = _run_streaming_command(args, cwd, env, callback)
        else:
            completed = subprocess.run(
                [str(arg) for arg in args],
                cwd=str(cwd) if cwd else None,
                env=dict(env) if env is not None else None,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = CommandResult(
                args=args,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            if recorder is not None and task_id != "-":
                if completed.stdout:
                    recorder.append_command_output(task_id, completed.stdout)
                if completed.stderr:
                    recorder.append_command_output(task_id, completed.stderr)
    except Exception as exc:
        _finish_diagnostic_command(task_id, recorder, command_id, started, None, error=str(exc))
        raise
    logger.info("Command exited with code %s", result.returncode)
    _finish_diagnostic_command(task_id, recorder, command_id, started, result.returncode)
    return result


def run_cancellable_command(
    args: Sequence[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    output_callback: Callable[[str], None] | None = None,
    cancellation: CommandCancellation | None = None,
    *,
    diagnostics: JobDiagnostics | None = None,
) -> CommandResult:
    token = cancellation or CommandCancellation()
    logger = get_logger()
    logger.info("Running cancellable command: %s", " ".join(redact_command(args)))
    task_id, recorder, command_id, started = _start_diagnostic_command(args, cwd, diagnostics)
    callback = _diagnostic_output_callback(task_id, recorder, output_callback)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [str(arg) for arg in args],
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except Exception as exc:
        _finish_diagnostic_command(task_id, recorder, command_id, started, None, error=str(exc))
        raise
    token._attach(process)
    try:
        output = _read_streaming_output(process, callback)
        returncode = process.wait()
    except Exception as exc:
        _terminate_process_tree(process)
        process.wait()
        _finish_diagnostic_command(task_id, recorder, command_id, started, process.returncode, error=str(exc))
        raise
    finally:
        token._detach(process)
    logger.info("Cancellable command exited with code %s", returncode)
    result = CommandResult(
        args=args,
        returncode=returncode,
        stdout="",
        stderr=output,
        cancelled=token.is_requested,
    )
    _finish_diagnostic_command(
        task_id,
        recorder,
        command_id,
        started,
        returncode,
        cancelled=result.cancelled,
    )
    return result


def _run_streaming_command(
    args: Sequence[str],
    cwd: Path | None,
    env: Mapping[str, str] | None,
    output_callback: Callable[[str], None],
) -> CommandResult:
    logger = get_logger()
    process = subprocess.Popen(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    output = _read_streaming_output(process, output_callback)
    returncode = process.wait()
    logger.info("Command exited with code %s", returncode)
    return CommandResult(args=args, returncode=returncode, stdout="", stderr=output)


def _read_streaming_output(
    process: subprocess.Popen[str],
    output_callback: Callable[[str], None] | None,
) -> str:
    output_parts: list[str] = []
    segment_parts: list[str] = []
    if process.stdout is not None:
        try:
            while True:
                char = process.stdout.read(1)
                if char == "":
                    break
                output_parts.append(char)
                if char in "\r\n":
                    _emit_output_segment(segment_parts, output_callback)
                else:
                    segment_parts.append(char)
        finally:
            process.stdout.close()
    _emit_output_segment(segment_parts, output_callback)
    return "".join(output_parts)


def _emit_output_segment(
    segment_parts: list[str],
    output_callback: Callable[[str], None] | None,
) -> None:
    segment = "".join(segment_parts).strip()
    segment_parts.clear()
    if segment and output_callback is not None:
        output_callback(segment)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _start_diagnostic_command(
    args: Sequence[str],
    cwd: Path | None,
    diagnostics: JobDiagnostics | None,
) -> tuple[str, JobDiagnostics | None, str, float]:
    task_id = current_task_id()
    recorder = diagnostics
    if recorder is None and task_id != "-":
        recorder = get_job_diagnostics()
    command_id = recorder.start_command(task_id, args, cwd) if recorder is not None and task_id != "-" else ""
    return task_id, recorder, command_id, monotonic()


def _diagnostic_output_callback(
    task_id: str,
    diagnostics: JobDiagnostics | None,
    output_callback: Callable[[str], None] | None,
) -> Callable[[str], None] | None:
    if diagnostics is None and output_callback is None:
        return None

    def emit(line: str) -> None:
        if diagnostics is not None and task_id != "-":
            diagnostics.append_command_output(task_id, line)
        if output_callback is not None:
            output_callback(line)

    return emit


def _finish_diagnostic_command(
    task_id: str,
    diagnostics: JobDiagnostics | None,
    command_id: str,
    started: float,
    returncode: int | None,
    *,
    cancelled: bool = False,
    error: str = "",
) -> None:
    if diagnostics is None or task_id == "-" or not command_id:
        return
    diagnostics.finish_command(
        task_id,
        command_id,
        returncode=returncode,
        duration_seconds=monotonic() - started,
        cancelled=cancelled,
        error=error,
    )
