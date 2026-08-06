from __future__ import annotations

import re
import unicodedata
from pathlib import Path


_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_SEPARATOR_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_DISPLAY_INVALID_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE_PATTERN = re.compile(r"\s+")


def safe_filename_stem(value: str, fallback: str = "audio", max_length: int = 72) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    stem = _SEPARATOR_PATTERN.sub("_", ascii_value).strip("._-").lower()
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        stem = fallback
    if stem.casefold() in _RESERVED_WINDOWS_NAMES:
        stem = f"{stem}_file"
    return stem[:max_length].rstrip("._-") or fallback


def safe_display_filename_stem(
    value: str,
    fallback: str = "audio",
    max_length: int = 112,
) -> str:
    normalized = unicodedata.normalize("NFKC", value.strip())
    stem = _DISPLAY_INVALID_PATTERN.sub(" ", normalized)
    stem = _WHITESPACE_PATTERN.sub(" ", stem).strip(" .")
    if not stem:
        stem = fallback
    if stem.casefold() in _RESERVED_WINDOWS_NAMES:
        stem = f"{stem}_file"
    return stem[:max_length].rstrip(" .") or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def unique_display_path(path: Path) -> Path:
    if not path.exists():
        return path

    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1
