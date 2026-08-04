from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path


def copy_file_atomic(
    source: Path,
    target: Path,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    source_size = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    if source == target:
        _report(progress, source_size)
        return target
    if (
        target.is_file()
        and target.stat().st_size == source_size
        and target.stat().st_mtime_ns == source.stat().st_mtime_ns
    ):
        _report(progress, source_size)
        return target

    temporary = target.with_suffix(f"{target.suffix}.copying")
    copied = 0
    try:
        with source.open("rb") as source_file, temporary.open("wb") as target_file:
            while chunk := source_file.read(8 * 1024 * 1024):
                target_file.write(chunk)
                copied += len(chunk)
                _report(progress, copied)
        os.replace(temporary, target)
        shutil.copystat(source, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def link_or_copy_file(
    source: Path,
    target: Path,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    source_size = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    if source == target:
        _report(progress, source_size)
        return target
    if (
        target.is_file()
        and target.stat().st_size == source_size
        and target.stat().st_mtime_ns == source.stat().st_mtime_ns
    ):
        _report(progress, source_size)
        return target

    temporary = target.with_suffix(f"{target.suffix}.linking")
    try:
        if temporary.exists():
            temporary.unlink()
        os.link(source, temporary)
        os.replace(temporary, target)
        _report(progress, source_size)
        return target
    except OSError:
        if temporary.exists():
            temporary.unlink()
        return copy_file_atomic(source, target, progress)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.expanduser().resolve().open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(value)
