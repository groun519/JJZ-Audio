from __future__ import annotations

import shutil
import sys
from pathlib import Path


class YouTubeRuntimeError(RuntimeError):
    """Raised when the JavaScript runtime required by YouTube is unavailable."""


def youtube_dl_runtime_options() -> dict[str, object]:
    return {"js_runtimes": {"deno": {"path": str(resolve_deno_executable())}}}


def resolve_deno_executable() -> Path:
    for candidate in _bundled_deno_candidates():
        if candidate.is_file():
            return candidate.resolve()

    installed = shutil.which("deno")
    if installed:
        return Path(installed).resolve()

    try:
        from deno import find_deno_bin

        candidate = Path(find_deno_bin())
    except (FileNotFoundError, ImportError):
        candidate = None
    if candidate is not None and candidate.is_file():
        return candidate.resolve()

    raise YouTubeRuntimeError(
        "The YouTube download runtime is incomplete. Reinstall or update JJZero Audio."
    )


def _bundled_deno_candidates() -> tuple[Path, ...]:
    executable_dir = Path(sys.executable).resolve().parent
    bundle_dir = Path(getattr(sys, "_MEIPASS", executable_dir))
    return (
        bundle_dir / "deno.exe",
        bundle_dir / "bin" / "deno.exe",
        executable_dir / "deno.exe",
        executable_dir / "_internal" / "deno.exe",
        executable_dir / "_internal" / "bin" / "deno.exe",
    )
