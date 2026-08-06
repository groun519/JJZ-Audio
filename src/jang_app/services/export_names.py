from __future__ import annotations

import re
from pathlib import Path
from re import Pattern

from jang_app.services.file_names import safe_display_filename_stem, unique_display_path


def next_song_export_path(
    output_dir: Path,
    song_title: str,
    asset_name: str,
    extension: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    title = safe_display_filename_stem(song_title, fallback="Untitled", max_length=80)
    asset = safe_display_filename_stem(asset_name, fallback="Export", max_length=24)
    suffix = extension if extension.startswith(".") else f".{extension}"
    return unique_display_path(output_dir / f"{title} - {asset}{suffix.lower()}")


def migrate_legacy_song_exports(
    output_dir: Path,
    song_title: str,
    asset_name: str,
    extension: str,
    legacy_pattern: Pattern[str],
) -> None:
    if not output_dir.is_dir():
        return
    legacy_files = sorted(
        (
            path
            for path in output_dir.iterdir()
            if path.is_file() and legacy_pattern.fullmatch(path.name)
        ),
        key=_modified_time,
    )
    for legacy_path in legacy_files:
        target = next_song_export_path(output_dir, song_title, asset_name, extension)
        try:
            legacy_path.rename(target)
        except OSError:
            continue


def timestamp_export_pattern(prefix: str, extension: str) -> Pattern[str]:
    escaped_extension = re.escape(extension.lstrip("."))
    return re.compile(
        rf"{re.escape(prefix)}-\d{{8}}-\d{{6}}(?:-\d{{3}})?\.{escaped_extension}",
        re.IGNORECASE,
    )


def _modified_time(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
