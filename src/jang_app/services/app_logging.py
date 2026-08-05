from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from jang_app.config import LOG_DIR, LOG_FILE
from jang_app.services.job_diagnostics import SESSION_ID, current_task_id


LOGGER_NAME = "jang_app"
_exception_logging_installed = False
_crash_stream: TextIO | None = None


class _DiagnosticContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = SESSION_ID
        record.task_id = current_task_id()
        return True


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
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
    return logger


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
