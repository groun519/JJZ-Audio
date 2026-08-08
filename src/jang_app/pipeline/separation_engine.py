from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jang_app.services.separation_recipe import SeparationRecipe


ProgressCallback = Callable[[int], None]


class SeparationError(RuntimeError):
    """Raised when source separation cannot be completed."""


@dataclass(frozen=True)
class SeparationRequest:
    input_path: Path
    output_root: Path
    recipe: SeparationRecipe


@dataclass(frozen=True)
class SeparationResult:
    input_path: Path
    job_dir: Path
    vocals_path: Path
    accompaniment_path: Path
    recipe: SeparationRecipe


class SeparationEngine(Protocol):
    engine_id: str

    def separate(
        self,
        request: SeparationRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult: ...
