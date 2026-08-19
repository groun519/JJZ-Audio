from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import VOCAL_SPLIT_MODEL_DIR
from jang_app.services.app_update import ReleaseArtifact, UpdateError, download_artifact


VOCAL_SPLIT_MODEL = "5_HP-Karaoke-UVR.pth"
VOCAL_SPLIT_MODEL_URL = (
    "https://github.com/TRvlvr/model_repo/releases/download/"
    "all_public_uvr_models/5_HP-Karaoke-UVR.pth"
)
VOCAL_SPLIT_MODEL_SIZE = 126_782_699
VOCAL_SPLIT_MODEL_SHA256 = (
    "fe00891defbb61f4261500af22f7624f1a3df8dc75fa3998d1aece02e6be4537"
)


@dataclass(frozen=True)
class VocalSplitAssetStatus:
    ready: bool
    missing_bytes: int


class VocalSplitAssetError(RuntimeError):
    pass


def vocal_split_asset_status(
    model_root: Path = VOCAL_SPLIT_MODEL_DIR,
) -> VocalSplitAssetStatus:
    target = model_root.expanduser().resolve() / VOCAL_SPLIT_MODEL
    ready = _file_has_size(target, VOCAL_SPLIT_MODEL_SIZE)
    return VocalSplitAssetStatus(ready, 0 if ready else VOCAL_SPLIT_MODEL_SIZE)


def prepare_vocal_split_model(
    model_root: Path = VOCAL_SPLIT_MODEL_DIR,
    progress: Callable[[int], None] | None = None,
) -> Path:
    root = model_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        return download_artifact(
            ReleaseArtifact(
                name=VOCAL_SPLIT_MODEL,
                size=VOCAL_SPLIT_MODEL_SIZE,
                sha256=VOCAL_SPLIT_MODEL_SHA256,
                url=VOCAL_SPLIT_MODEL_URL,
            ),
            root,
            progress=progress,
            timeout=300.0,
        )
    except UpdateError as exc:
        raise VocalSplitAssetError(
            f"Could not prepare the vocal separation model: {exc}"
        ) from exc


def _file_has_size(path: Path, expected_size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == expected_size
    except OSError:
        return False
