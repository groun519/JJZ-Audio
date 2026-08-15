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
    python_path_parts = (
        str(root),
        environment.get("PYTHONPATH", ""),
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in python_path_parts if part
    )
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8:replace"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONFAULTHANDLER"] = "1"
    environment["RVC_CUDA_GRAPH"] = "0"
    environment["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    environment["NUMEXPR_NUM_THREADS"] = "1"
    return environment
