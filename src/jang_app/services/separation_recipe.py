from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from jang_app.services.managed_files import write_json_atomic


SEPARATION_RUN_MANIFEST = "separation.json"
SEPARATION_RUN_SCHEMA = 2
_SUPPORTED_SEPARATION_RUN_SCHEMAS = {1, SEPARATION_RUN_SCHEMA}


@dataclass(frozen=True)
class SeparationRecipe:
    recipe_id: str
    label: str
    engine: str
    model: str
    shifts: int = 1
    overlap: float = 0.25
    float32: bool = False
    clip_mode: str = "rescale"
    mixture_consistency: bool = False
    ensemble_models: tuple[str, ...] = ()
    ensemble_weights: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.recipe_id.strip() or not self.label.strip():
            raise ValueError("Separation recipe identity is required")
        if self.engine != "demucs":
            raise ValueError(f"Unsupported separation engine: {self.engine}")
        if not self.model.strip():
            raise ValueError("Separation model is required")
        if self.shifts < 0:
            raise ValueError("Separation shifts cannot be negative")
        if not 0.0 <= self.overlap < 1.0:
            raise ValueError("Separation overlap must be between 0 and 1")
        if self.clip_mode not in {"rescale", "clamp"}:
            raise ValueError(f"Unsupported separation clip mode: {self.clip_mode}")
        models = tuple(str(model).strip() for model in self.ensemble_models)
        weights = tuple(float(weight) for weight in self.ensemble_weights)
        object.__setattr__(self, "ensemble_models", models)
        object.__setattr__(self, "ensemble_weights", weights)
        if models and (len(models) < 2 or any(not model for model in models)):
            raise ValueError("A separation ensemble requires at least two named models")
        if len(set(models)) != len(models):
            raise ValueError("Separation ensemble models must be unique")
        if weights and len(weights) != len(models):
            raise ValueError("Separation ensemble weights must match its models")
        if any(weight <= 0 for weight in weights):
            raise ValueError("Separation ensemble weights must be positive")
        if weights and not models:
            raise ValueError("Separation ensemble weights require ensemble models")

    @property
    def models(self) -> tuple[str, ...]:
        return self.ensemble_models or (self.model,)

    @property
    def is_ensemble(self) -> bool:
        return len(self.models) > 1

    @property
    def normalized_ensemble_weights(self) -> tuple[float, ...]:
        weights = self.ensemble_weights or tuple(1.0 for _model in self.models)
        total = sum(weights)
        return tuple(weight / total for weight in weights)

    @property
    def summary(self) -> str:
        precision = "32-bit float" if self.float32 else "16-bit"
        consistency = " / mix-consistent" if self.mixture_consistency else ""
        models = " + ".join(self.models)
        ensemble = f" / ensemble {len(self.models)}" if self.is_ensemble else ""
        return (
            f"{models}{ensemble} / shifts {self.shifts} / overlap {self.overlap:.2f} / "
            f"{precision}{consistency}"
        )


@dataclass(frozen=True)
class SeparationRun:
    recipe: SeparationRecipe
    created_at: str
    source_name: str = ""
    postprocess_status: str = "not_requested"
    postprocess_detail: str = ""


STANDARD_RECIPE = SeparationRecipe(
    recipe_id="demucs-standard-v1",
    label="Standard",
    engine="demucs",
    model="htdemucs",
    shifts=1,
    overlap=0.25,
    float32=True,
    mixture_consistency=False,
)

HIGH_QUALITY_RECIPE = SeparationRecipe(
    recipe_id="demucs-high-quality-v1",
    label="High Quality",
    engine="demucs",
    model="htdemucs_ft",
    shifts=2,
    overlap=0.50,
    float32=True,
    mixture_consistency=True,
)

MAXIMUM_RECIPE = SeparationRecipe(
    recipe_id="demucs-maximum-v1",
    label="Maximum",
    engine="demucs",
    model="htdemucs_ft",
    shifts=4,
    overlap=0.50,
    float32=True,
    mixture_consistency=True,
    ensemble_models=("htdemucs_ft", "htdemucs"),
    ensemble_weights=(0.5, 0.5),
)

SEPARATION_RECIPES = (STANDARD_RECIPE, HIGH_QUALITY_RECIPE, MAXIMUM_RECIPE)


def separation_recipe(recipe_id: str) -> SeparationRecipe:
    return next(
        (recipe for recipe in SEPARATION_RECIPES if recipe.recipe_id == recipe_id),
        STANDARD_RECIPE,
    )


def save_separation_run(
    job_dir: Path,
    recipe: SeparationRecipe,
    source_name: str,
    *,
    postprocess_status: str = "not_requested",
    postprocess_detail: str = "",
) -> Path:
    target = job_dir.expanduser().resolve() / SEPARATION_RUN_MANIFEST
    write_json_atomic(
        target,
        {
            "schema": SEPARATION_RUN_SCHEMA,
            "created_at": datetime.now(UTC).isoformat(),
            "source_name": source_name,
            "recipe": asdict(recipe),
            "postprocess": {
                "status": postprocess_status,
                "detail": postprocess_detail,
            },
        },
    )
    return target


def load_separation_run(job_dir: Path) -> SeparationRun:
    root = job_dir.expanduser().resolve()
    manifest = root / SEPARATION_RUN_MANIFEST
    if not manifest.is_file():
        return _legacy_run(root)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            not isinstance(data, Mapping)
            or data.get("schema") not in _SUPPORTED_SEPARATION_RUN_SCHEMAS
        ):
            return _legacy_run(root)
        recipe_data = data.get("recipe")
        if not isinstance(recipe_data, Mapping):
            return _legacy_run(root)
        recipe = SeparationRecipe(
            recipe_id=str(recipe_data["recipe_id"]),
            label=str(recipe_data["label"]),
            engine=str(recipe_data["engine"]),
            model=str(recipe_data["model"]),
            shifts=int(recipe_data.get("shifts", 1)),
            overlap=float(recipe_data.get("overlap", 0.25)),
            float32=bool(recipe_data.get("float32", False)),
            clip_mode=str(recipe_data.get("clip_mode", "rescale")),
            mixture_consistency=bool(recipe_data.get("mixture_consistency", False)),
            ensemble_models=tuple(recipe_data.get("ensemble_models", ())),
            ensemble_weights=tuple(recipe_data.get("ensemble_weights", ())),
        )
        postprocess_data = data.get("postprocess")
        if not isinstance(postprocess_data, Mapping):
            postprocess_data = {}
        return SeparationRun(
            recipe=recipe,
            created_at=str(data.get("created_at", "")),
            source_name=str(data.get("source_name", "")),
            postprocess_status=str(postprocess_data.get("status", "not_requested")),
            postprocess_detail=str(postprocess_data.get("detail", "")),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return _legacy_run(root)


def _legacy_run(job_dir: Path) -> SeparationRun:
    model = job_dir.parent.name or "htdemucs"
    recipe = SeparationRecipe(
        recipe_id=f"legacy-{model}",
        label="Legacy",
        engine="demucs",
        model=model,
    )
    try:
        created_at = datetime.fromtimestamp(job_dir.stat().st_mtime, UTC).isoformat()
    except OSError:
        created_at = ""
    return SeparationRun(recipe=recipe, created_at=created_at)
