from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread

from jang_app.services.app_logging import get_logger


class LiveTextFile:
    """Follow lines appended to a text file without blocking the caller."""

    def __init__(
        self,
        path: Path,
        start_offset: int,
        line_callback: Callable[[str], None],
        *,
        poll_seconds: float = 0.2,
    ) -> None:
        self._path = path
        self._position = max(0, int(start_offset))
        self._line_callback = line_callback
        self._poll_seconds = max(0.05, float(poll_seconds))
        self._pending = b""
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._follow,
            name=f"follow-{self._path.name}",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self._poll_seconds * 4))
        self._read_available(flush=True)

    def __enter__(self) -> LiveTextFile:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _follow(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            self._read_available()

    def _read_available(self, *, flush: bool = False) -> None:
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size < self._position:
            self._position = 0
            self._pending = b""
        try:
            with self._path.open("rb") as source:
                source.seek(self._position)
                appended = source.read()
        except OSError:
            return
        self._position += len(appended)
        segments = (self._pending + appended).split(b"\n")
        self._pending = segments.pop() if segments else b""
        for segment in segments:
            self._emit(segment.rstrip(b"\r"))
        if flush and self._pending:
            self._emit(self._pending.rstrip(b"\r"))
            self._pending = b""

    def _emit(self, data: bytes) -> None:
        line = data.decode("utf-8", errors="replace").strip()
        if not line:
            return
        try:
            self._line_callback(line)
        except Exception as exc:
            get_logger().warning("Live text callback failed for %s: %s", self._path, exc)
