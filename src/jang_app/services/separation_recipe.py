from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping

from jang_app.services.managed_files import write_json_atomic


SEPARATION_RUN_MANIFEST = "separation.json"
SEPARATION_RUN_SCHEMA = 4
_SUPPORTED_SEPARATION_RUN_SCHEMAS = {1, 2, 3, SEPARATION_RUN_SCHEMA}


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
    effect_model: str = ""
    vocal_recipe_id: str = ""
    instrumental_recipe_id: str = ""

    def __post_init__(self) -> None:
        if not self.recipe_id.strip() or not self.label.strip():
            raise ValueError("Separation recipe identity is required")
        if self.engine not in {"demucs", "roformer", "composite"}:
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
        effect_model = str(self.effect_model).strip()
        object.__setattr__(self, "effect_model", effect_model)
        if effect_model and self.engine != "roformer":
            raise ValueError("Effect removal requires the RoFormer separation engine")
        vocal_recipe_id = str(self.vocal_recipe_id).strip()
        instrumental_recipe_id = str(self.instrumental_recipe_id).strip()
        object.__setattr__(self, "vocal_recipe_id", vocal_recipe_id)
        object.__setattr__(self, "instrumental_recipe_id", instrumental_recipe_id)
        if self.engine == "composite":
            if not vocal_recipe_id or not instrumental_recipe_id:
                raise ValueError("Composite separation requires vocal and instrumental recipes")
            if models or weights or effect_model:
                raise ValueError("Composite separation cannot define direct model stages")
        elif vocal_recipe_id or instrumental_recipe_id:
            raise ValueError("Component recipe IDs require the composite separation engine")

    @property
    def models(self) -> tuple[str, ...]:
        if self.is_composite:
            return _unique_models(
                model
                for recipe in self.component_recipes
                for model in recipe.models
            )
        return self.ensemble_models or (self.model,)

    @property
    def required_models(self) -> tuple[str, ...]:
        if self.is_composite:
            return _unique_models(
                model
                for recipe in self.component_recipes
                for model in recipe.required_models
            )
        if not self.effect_model:
            return self.models
        return (*self.models, self.effect_model)

    @property
    def is_ensemble(self) -> bool:
        return len(self.models) > 1

    @property
    def is_composite(self) -> bool:
        return self.engine == "composite"

    @property
    def component_recipes(self) -> tuple[SeparationRecipe, SeparationRecipe]:
        if not self.is_composite:
            raise ValueError("Only composite separation has component recipes")
        return (
            custom_component_recipe(self.vocal_recipe_id),
            custom_component_recipe(self.instrumental_recipe_id),
        )

    @property
    def normalized_ensemble_weights(self) -> tuple[float, ...]:
        if self.is_composite:
            raise ValueError("Composite separation has no ensemble weights")
        weights = self.ensemble_weights or tuple(1.0 for _model in self.models)
        total = sum(weights)
        return tuple(weight / total for weight in weights)

    @property
    def summary(self) -> str:
        if self.is_composite:
            vocal_recipe, instrumental_recipe = self.component_recipes
            return (
                f"vocal: {custom_component_label(vocal_recipe)} / "
                f"instrumental: {custom_component_label(instrumental_recipe)}"
            )
        if self.engine == "roformer":
            consistency = " / mix-consistent" if self.mixture_consistency else ""
            effect = f" -> {self.effect_model}" if self.effect_model else ""
            return f"{self.model}{effect} / vocal 2-stem / 32-bit float{consistency}"
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


FAST_RECIPE = SeparationRecipe(
    recipe_id="demucs-standard-v1",
    label="Fast Separation",
    engine="demucs",
    model="htdemucs",
    shifts=1,
    overlap=0.25,
    float32=True,
    mixture_consistency=False,
)

PRECISION_RECIPE = SeparationRecipe(
    recipe_id="roformer-precision-v1",
    label="Precision Separation",
    engine="roformer",
    model="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    shifts=1,
    overlap=0.25,
    float32=True,
    mixture_consistency=True,
)

VOCAL_MELBAND_RECIPE = SeparationRecipe(
    recipe_id="roformer-vocal-melband-v1",
    label="Precision Separation",
    engine="roformer",
    model="MelBandRoformer.ckpt",
    shifts=1,
    overlap=0.25,
    float32=True,
    mixture_consistency=True,
)

EFFECT_REMOVAL_RECIPE = SeparationRecipe(
    recipe_id="roformer-effect-removal-v1",
    label="Precision Separation · Effect Removal",
    engine="roformer",
    model="MelBandRoformer.ckpt",
    shifts=1,
    overlap=0.25,
    float32=True,
    mixture_consistency=True,
    effect_model="deverb_bs_roformer_8_256dim_8depth.ckpt",
)

PRECISION_RECIPES = (
    PRECISION_RECIPE,
    VOCAL_MELBAND_RECIPE,
    EFFECT_REMOVAL_RECIPE,
)

CUSTOM_COMPONENT_RECIPES = (
    VOCAL_MELBAND_RECIPE,
    FAST_RECIPE,
)


def custom_component_recipe(recipe_id: str) -> SeparationRecipe:
    recipe = next(
        (item for item in CUSTOM_COMPONENT_RECIPES if item.recipe_id == recipe_id),
        None,
    )
    if recipe is None:
        raise ValueError(f"Unsupported custom separation component: {recipe_id}")
    return recipe


def custom_component_label(recipe: SeparationRecipe) -> str:
    if recipe.recipe_id == VOCAL_MELBAND_RECIPE.recipe_id:
        return "Vocal MelBand (Kim)"
    if recipe.recipe_id == FAST_RECIPE.recipe_id:
        return "HTDemucs"
    return recipe.label


def custom_separation_recipe(
    vocal_recipe_id: str,
    instrumental_recipe_id: str,
) -> SeparationRecipe:
    vocal_recipe = custom_component_recipe(vocal_recipe_id)
    instrumental_recipe = custom_component_recipe(instrumental_recipe_id)
    return SeparationRecipe(
        recipe_id="custom-separation-v1",
        label="Custom Separation",
        engine="composite",
        model="custom",
        float32=True,
        vocal_recipe_id=vocal_recipe.recipe_id,
        instrumental_recipe_id=instrumental_recipe.recipe_id,
    )


CUSTOM_RECIPE = custom_separation_recipe(
    VOCAL_MELBAND_RECIPE.recipe_id,
    FAST_RECIPE.recipe_id,
)

_LEGACY_HIGH_QUALITY_RECIPE = SeparationRecipe(
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

# Keep the old names import-compatible while the product UI moves away from
# quality tiers. Legacy recipe IDs remain readable but are not shown in the UI.
STANDARD_RECIPE = FAST_RECIPE
HIGH_QUALITY_RECIPE = PRECISION_RECIPE
SEPARATION_RECIPES = (FAST_RECIPE, VOCAL_MELBAND_RECIPE, CUSTOM_RECIPE)
KNOWN_SEPARATION_RECIPES = (
    FAST_RECIPE,
    PRECISION_RECIPE,
    VOCAL_MELBAND_RECIPE,
    EFFECT_REMOVAL_RECIPE,
    CUSTOM_RECIPE,
    _LEGACY_HIGH_QUALITY_RECIPE,
    MAXIMUM_RECIPE,
)


def separation_recipe(recipe_id: str) -> SeparationRecipe:
    return next(
        (recipe for recipe in KNOWN_SEPARATION_RECIPES if recipe.recipe_id == recipe_id),
        FAST_RECIPE,
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
            effect_model=str(recipe_data.get("effect_model", "")),
            vocal_recipe_id=str(recipe_data.get("vocal_recipe_id", "")),
            instrumental_recipe_id=str(
                recipe_data.get("instrumental_recipe_id", "")
            ),
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


def _unique_models(models: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(model) for model in models))
