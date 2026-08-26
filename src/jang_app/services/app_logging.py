from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from jang_app.config import LOG_DIR, LOG_FILE
from jang_app.services.job_diagnostics import SESSION_ID, current_task_id
from jang_app.version import __version__


LOGGER_NAME = "jang_app"
_exception_logging_installed = False
_crash_stream: TextIO | None = None
_ROLLOVER_RETRY_SECONDS = 60.0


class _WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """Keep logging when another Windows process temporarily owns a backup file."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rollover_retry_after = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802
        if time.monotonic() < self._rollover_retry_after:
            return False
        return super().shouldRollover(record)

    def doRollover(self) -> None:  # noqa: N802
        try:
            super().doRollover()
        except OSError:
            # Windows cannot rename jang.log while an older app/test process still
            # has it open. Continue appending and retry rotation after a cooldown.
            self._rollover_retry_after = time.monotonic() + _ROLLOVER_RETRY_SECONDS
            if self.stream is None and not self.delay:
                self.stream = self._open()


class _DiagnosticContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = SESSION_ID
        record.task_id = current_task_id()
        return True


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = _WindowsSafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.addFilter(_DiagnosticContextFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s "
                "[session=%(session_id)s task=%(task_id)s]: %(message)s"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.info(
            "Application session started | version=%s | revision=%s | mode=%s | python=%s | executable=%s",
            __version__,
            _build_revision(),
            "packaged" if getattr(sys, "frozen", False) else "source",
            sys.version.split()[0],
            Path(sys.executable).resolve(),
        )
    return logger


def _build_revision() -> str:
    if not getattr(sys, "frozen", False):
        return "source"
    marker = Path(sys.executable).resolve().parent / "build-provenance.json"
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    revision = data.get("source_revision") if isinstance(data, dict) else None
    return str(revision) if isinstance(revision, str) and revision else "unknown"


def install_exception_logging() -> None:
    global _crash_stream, _exception_logging_installed
    if _exception_logging_installed:
        return
    _exception_logging_installed = True
    logger = get_logger()

    def handle_exception(exception_type, exception, traceback) -> None:
        logger.critical(
            "Unhandled application exception",
            exc_info=(exception_type, exception, traceback),
        )
        sys.__excepthook__(exception_type, exception, traceback)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled thread exception in %s",
            args.thread.name if args.thread is not None else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    try:
        crash_path = Path(LOG_DIR) / f"crash-{SESSION_ID}.log"
        crash_path.parent.mkdir(parents=True, exist_ok=True)
        _crash_stream = crash_path.open("a", encoding="utf-8")
        faulthandler.enable(_crash_stream, all_threads=True)
    except (OSError, RuntimeError):
        _crash_stream = None
