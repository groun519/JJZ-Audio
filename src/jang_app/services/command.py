from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from jang_app.services.app_logging import get_logger


@dataclass(frozen=True)
class CommandResult:
    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stderr or self.stdout).strip()


def run_command(
    args: Sequence[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> CommandResult:
    logger = get_logger()
    logger.info("Running command: %s", " ".join(str(arg) for arg in args))
    if output_callback is not None:
        return _run_streaming_command(args, cwd, env, output_callback)

    completed = subprocess.run(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.info("Command exited with code %s", completed.returncode)
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


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
    )

    output_parts: list[str] = []
    segment_parts: list[str] = []
    if process.stdout is not None:
        while True:
            char = process.stdout.read(1)
            if char == "":
                break

            output_parts.append(char)
            if char in "\r\n":
                _emit_output_segment(segment_parts, output_callback)
            else:
                segment_parts.append(char)

    _emit_output_segment(segment_parts, output_callback)
    returncode = process.wait()
    output = "".join(output_parts)
    logger.info("Command exited with code %s", returncode)
    return CommandResult(args=args, returncode=returncode, stdout="", stderr=output)


def _emit_output_segment(segment_parts: list[str], output_callback: Callable[[str], None]) -> None:
    segment = "".join(segment_parts).strip()
    segment_parts.clear()
    if segment:
        output_callback(segment)
