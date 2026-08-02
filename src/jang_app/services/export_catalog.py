from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    size_bytes: int
    modified_at: float


def list_exported_files(output_dir: Path, pattern: str) -> tuple[ExportedFile, ...]:
    if not output_dir.is_dir():
        return ()

    exports: list[ExportedFile] = []
    for path in output_dir.glob(pattern):
        try:
            stat = path.stat()
        except OSError:
            continue
        exports.append(ExportedFile(path.resolve(), stat.st_size, stat.st_mtime))
    return tuple(sorted(exports, key=lambda item: item.modified_at, reverse=True))
