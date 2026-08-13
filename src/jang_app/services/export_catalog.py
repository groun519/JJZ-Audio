from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.file_names import safe_display_filename_stem, unique_display_path


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    size_bytes: int
    modified_at: float


def list_exported_files(
    output_dir: Path,
    pattern: str | Sequence[str],
) -> tuple[ExportedFile, ...]:
    if not output_dir.is_dir():
        return ()

    exports: list[ExportedFile] = []
    patterns = (pattern,) if isinstance(pattern, str) else tuple(pattern)
    paths = (path for current in patterns for path in output_dir.glob(current))
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        exports.append(ExportedFile(path.resolve(), stat.st_size, stat.st_mtime))
    return tuple(sorted(exports, key=lambda item: item.modified_at, reverse=True))


def rename_exported_file(source: Path, name: str) -> Path:
    resolved = source.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Exported file does not exist: {resolved}")

    requested_name = name.strip()
    if Path(requested_name).suffix.casefold() == resolved.suffix.casefold():
        requested_name = Path(requested_name).stem
    stem = safe_display_filename_stem(requested_name, fallback=resolved.stem)
    target = resolved.with_name(f"{stem}{resolved.suffix.lower()}")
    if target == resolved:
        return resolved
    target = unique_display_path(target)
    resolved.rename(target)
    return target.resolve()
