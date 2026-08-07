from __future__ import annotations


__version__ = "0.2.6"


def version_tuple() -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in __version__.split("."))
    return major, minor, patch
