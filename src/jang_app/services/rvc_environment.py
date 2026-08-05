from __future__ import annotations

import os
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR


def build_rvc_environment(rvc_root: Path) -> dict[str, str]:
    root = rvc_root.expanduser().resolve()
    environment = os.environ.copy()
    path_parts = (
        str(FFMPEG_BIN_DIR),
        str(root),
        str(root / "runtime"),
        environment.get("PATH", ""),
    )
    environment["PATH"] = os.pathsep.join(part for part in path_parts if part)
    environment["PYTHONFAULTHANDLER"] = "1"
    return environment
