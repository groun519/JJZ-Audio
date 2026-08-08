from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jang_app.config import DEMUCS_RUNTIME_DIR
from jang_app.services.separation_recipe import SeparationRecipe


_CHECKPOINT_BYTES = 84_141_911
_DEMUCS_MODEL_FILES = {
    "htdemucs": ("955717e8-8726e21a.th",),
    "htdemucs_ft": (
        "f7e0c4bc-ba3fe64a.th",
        "d12395a8-e57c48e6.th",
        "92cfc3b6-ef3bcb9c.th",
        "04573f0d-f3cf25b2.th",
    ),
}


@dataclass(frozen=True)
class SeparationAssetStatus:
    model: str
    ready: bool
    present_files: int
    required_files: int
    missing_bytes: int

    @property
    def status_text(self) -> str:
        if self.ready:
            return "Model ready"
        return f"First use downloads about {format_byte_size(self.missing_bytes)}"


def separation_asset_status(
    model: str,
    runtime_root: Path = DEMUCS_RUNTIME_DIR,
) -> SeparationAssetStatus:
    files = _DEMUCS_MODEL_FILES.get(model, ())
    checkpoint_root = runtime_root.expanduser().resolve() / "torch" / "hub" / "checkpoints"
    present = tuple(filename for filename in files if (checkpoint_root / filename).is_file())
    missing_count = len(files) - len(present)
    return SeparationAssetStatus(
        model=model,
        ready=bool(files) and missing_count == 0,
        present_files=len(present),
        required_files=len(files),
        missing_bytes=missing_count * _CHECKPOINT_BYTES,
    )


def separation_model_component_count(model: str) -> int:
    return max(1, len(_DEMUCS_MODEL_FILES.get(model, ())))


def separation_recipe_asset_status(
    recipe: SeparationRecipe,
    runtime_root: Path = DEMUCS_RUNTIME_DIR,
) -> SeparationAssetStatus:
    return combine_separation_asset_status(
        separation_asset_status(model, runtime_root) for model in recipe.models
    )


def combine_separation_asset_status(
    statuses: Iterable[SeparationAssetStatus],
) -> SeparationAssetStatus:
    values = tuple(statuses)
    if not values:
        return SeparationAssetStatus("", False, 0, 0, 0)
    return SeparationAssetStatus(
        model=" + ".join(status.model for status in values),
        ready=all(status.ready for status in values),
        present_files=sum(status.present_files for status in values),
        required_files=sum(status.required_files for status in values),
        missing_bytes=sum(status.missing_bytes for status in values),
    )


def format_byte_size(byte_count: int) -> str:
    size = max(0, byte_count)
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB"
    return f"{size / 1024**2:.0f} MB"
