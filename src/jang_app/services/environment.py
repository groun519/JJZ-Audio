from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


class MissingExecutableError(RuntimeError):
    """Raised when a required command-line executable is unavailable."""


def require_executable(name: str, install_hint: str, search_dirs: Iterable[Path] = ()) -> str:
    path = _find_executable(name, search_dirs)
    if path is None:
        raise MissingExecutableError(f"{name} is not available. {install_hint}")
    _prepend_to_path(Path(path).parent)
    return path


def _find_executable(name: str, search_dirs: Iterable[Path]) -> str | None:
    for directory in search_dirs:
        candidate = directory / _platform_executable_name(name)
        if candidate.exists():
            return str(candidate)
    path = shutil.which(name)
    return path


def _platform_executable_name(name: str) -> str:
    if os.name == "nt" and not name.lower().endswith(".exe"):
        return f"{name}.exe"
    return name


def _prepend_to_path(directory: Path) -> None:
    directory_text = str(directory)
    current_paths = os.environ.get("PATH", "").split(os.pathsep)
    if directory_text not in current_paths:
        os.environ["PATH"] = os.pathsep.join([directory_text, *current_paths])
