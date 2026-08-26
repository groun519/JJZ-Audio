from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


_COPY_CHUNK_SIZE = 8 * 1024 * 1024
_LOCK_DIRECTORY_NAME = "JJZeroAudio-file-locks"
_LOCKS_GUARD = threading.Lock()
_TARGET_LOCKS: dict[str, "_ManagedPathLock"] = {}


class _ManagedPathLock:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.thread_lock = threading.RLock()
        self.local = threading.local()

    @contextmanager
    def acquire(self) -> Iterator[None]:
        with self.thread_lock:
            depth = int(getattr(self.local, "depth", 0))
            if depth == 0:
                self.local.handle = _acquire_process_lock(self.lock_path)
            self.local.depth = depth + 1
            try:
                yield
            finally:
                remaining = int(self.local.depth) - 1
                self.local.depth = remaining
                if remaining == 0:
                    handle = self.local.handle
                    del self.local.handle
                    _release_process_lock(handle)


@contextmanager
def managed_path_lock(path: Path) -> Iterator[None]:
    """Serialize one managed target across threads and application processes."""

    target = path.expanduser().resolve()
    key = os.path.normcase(str(target))
    with _LOCKS_GUARD:
        lock = _TARGET_LOCKS.get(key)
        if lock is None:
            digest = hashlib.sha256(key.encode("utf-8", errors="surrogatepass")).hexdigest()
            lock = _ManagedPathLock(
                Path(tempfile.gettempdir()) / _LOCK_DIRECTORY_NAME / f"{digest}.lock"
            )
            _TARGET_LOCKS[key] = lock
    with lock.acquire():
        yield


@contextmanager
def atomic_output_path(
    path: Path,
    *,
    operation: str = "building",
) -> Iterator[Path]:
    """Yield a unique staging path and publish it atomically on success."""

    target = path.expanduser().resolve()
    with managed_path_lock(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = _temporary_path(target, operation)
        try:
            yield temporary
            _replace_with_retry(temporary, target)
            _sync_parent_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)


def copy_file_atomic(
    source: Path,
    target: Path,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    with managed_path_lock(target):
        source_stat = source.stat()
        source_size = source_stat.st_size
        target.parent.mkdir(parents=True, exist_ok=True)
        if source == target:
            _report(progress, source_size)
            return target
        if target.is_file():
            target_stat = target.stat()
            if (
                target_stat.st_size == source_size
                and target_stat.st_mtime_ns == source_stat.st_mtime_ns
            ):
                _report(progress, source_size)
                return target

        temporary = _temporary_path(target, "copying")
        copied = 0
        try:
            with source.open("rb") as source_file, temporary.open("xb") as target_file:
                while chunk := source_file.read(_COPY_CHUNK_SIZE):
                    target_file.write(chunk)
                    copied += len(chunk)
                    _report(progress, copied)
                _flush_file(target_file)
            shutil.copystat(source, temporary)
            _replace_with_retry(temporary, target)
            _sync_parent_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def link_or_copy_file(
    source: Path,
    target: Path,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    with managed_path_lock(target):
        source_stat = source.stat()
        source_size = source_stat.st_size
        target.parent.mkdir(parents=True, exist_ok=True)
        if source == target:
            _report(progress, source_size)
            return target
        if target.is_file():
            target_stat = target.stat()
            if (
                target_stat.st_size == source_size
                and target_stat.st_mtime_ns == source_stat.st_mtime_ns
            ):
                _report(progress, source_size)
                return target

        temporary = _temporary_path(target, "linking")
        try:
            os.link(source, temporary)
            _replace_with_retry(temporary, target)
            _sync_parent_directory(target.parent)
            _report(progress, source_size)
            return target
        except OSError:
            temporary.unlink(missing_ok=True)
            return copy_file_atomic(source, target, progress)
        finally:
            temporary.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.expanduser().resolve().open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, data: Mapping[str, object]) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    write_text_atomic(path, payload, encoding="utf-8")


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    with atomic_output_path(path, operation="writing") as temporary:
        with temporary.open("x", encoding=encoding, newline="") as output:
            output.write(text)
            _flush_file(output)


def _temporary_path(target: Path, operation: str) -> Path:
    return target.parent / (
        f".{target.name}.{operation}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
    )


def _flush_file(file_object) -> None:
    file_object.flush()
    os.fsync(file_object.fileno())


def _sync_parent_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = None
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _acquire_process_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.02)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle
    except Exception:
        handle.close()
        raise


def _release_process_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(value)


def _replace_with_retry(source: Path, target: Path, attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.02 * (2**attempt))
