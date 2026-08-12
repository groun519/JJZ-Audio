from __future__ import annotations

from pathlib import Path

from jang_app.config import SEPARATION_OUTPUT_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.pipeline.composite_separation_engine import CompositeSeparationEngine
from jang_app.pipeline.demucs_engine import DemucsEngine
from jang_app.pipeline.demucs_ensemble_engine import DemucsEnsembleEngine
from jang_app.pipeline.roformer_engine import RoFormerEngine
from jang_app.pipeline.separation_engine import (
    ProgressCallback,
    SeparationEngine,
    SeparationError,
    SeparationRequest,
    SeparationResult,
)
from jang_app.services.separation_recipe import STANDARD_RECIPE, SeparationRecipe


def separate_audio(
    input_path: Path,
    output_root: Path = SEPARATION_OUTPUT_DIR,
    model_name: str = "htdemucs",
    progress_callback: ProgressCallback | None = None,
    *,
    recipe: SeparationRecipe | None = None,
    engine: SeparationEngine | None = None,
) -> SeparationResult:
    source = input_path.expanduser().resolve()
    _validate_input_audio(source)
    selected_recipe = recipe or _legacy_recipe(model_name)
    selected_engine = engine or _engine_for_recipe(selected_recipe)
    if selected_engine.engine_id != selected_recipe.engine:
        raise SeparationError(
            f"Separation engine '{selected_engine.engine_id}' cannot run recipe "
            f"'{selected_recipe.engine}'."
        )
    return selected_engine.separate(
        SeparationRequest(source, output_root, selected_recipe),
        progress_callback,
    )


def _engine_for_recipe(recipe: SeparationRecipe) -> SeparationEngine:
    if recipe.engine == "composite":
        return CompositeSeparationEngine(_engine_for_recipe)
    if recipe.engine == "roformer":
        return RoFormerEngine()
    return DemucsEnsembleEngine() if recipe.is_ensemble else DemucsEngine()


def _validate_input_audio(source: Path) -> None:
    if not source.exists():
        raise SeparationError(f"Input file does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise SeparationError(f"Unsupported audio format: {source.suffix}. Supported: {supported}")


def _legacy_recipe(model_name: str) -> SeparationRecipe:
    return SeparationRecipe(
        recipe_id=(
            STANDARD_RECIPE.recipe_id
            if model_name == STANDARD_RECIPE.model
            else f"demucs-{model_name}"
        ),
        label=STANDARD_RECIPE.label if model_name == STANDARD_RECIPE.model else model_name,
        engine="demucs",
        model=model_name,
        shifts=STANDARD_RECIPE.shifts,
        overlap=STANDARD_RECIPE.overlap,
        float32=STANDARD_RECIPE.float32,
    )
