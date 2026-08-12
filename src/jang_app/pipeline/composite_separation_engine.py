from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jang_app.config import TOOL_WORKSPACE_DIR
from jang_app.pipeline.separation_engine import (
    ProgressCallback,
    SeparationEngine,
    SeparationRequest,
    SeparationResult,
)
from jang_app.services.app_logging import get_logger
from jang_app.services.separation_recipe import SeparationRecipe, save_separation_run
from jang_app.services.tool_workspace import ToolWorkspace


EngineFactory = Callable[[SeparationRecipe], SeparationEngine]


class CompositeSeparationEngine:
    """Build one stem pair from independently selected vocal and instrumental models."""

    engine_id = "composite"

    def __init__(self, engine_factory: EngineFactory) -> None:
        self._engine_factory = engine_factory

    def separate(
        self,
        request: SeparationRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult:
        source = request.input_path.expanduser().resolve()
        recipe = request.recipe
        vocal_recipe, instrumental_recipe = recipe.component_recipes
        unique_recipes = tuple(
            dict.fromkeys(
                (vocal_recipe.recipe_id, instrumental_recipe.recipe_id)
            )
        )
        recipes_by_id = {
            item.recipe_id: item for item in (vocal_recipe, instrumental_recipe)
        }
        component_results: dict[str, SeparationResult] = {}
        logger = get_logger()
        logger.info(
            "Starting custom separation: input=%s vocal_recipe=%s instrumental_recipe=%s",
            source,
            vocal_recipe.recipe_id,
            instrumental_recipe.recipe_id,
        )

        with ToolWorkspace(TOOL_WORKSPACE_DIR, "composite") as workspace:
            for index, recipe_id in enumerate(unique_recipes):
                component_recipe = recipes_by_id[recipe_id]
                component_results[recipe_id] = self._engine_factory(
                    component_recipe
                ).separate(
                    SeparationRequest(
                        input_path=source,
                        output_root=workspace.root / f"c{index}",
                        recipe=component_recipe,
                    ),
                    _component_progress_callback(
                        progress_callback,
                        index=index,
                        count=len(unique_recipes),
                    ),
                )

            job_dir = request.output_root.expanduser().resolve()
            vocals_path = workspace.publish_file(
                component_results[vocal_recipe.recipe_id].vocals_path,
                job_dir / "vocals.wav",
            )
            accompaniment_path = workspace.publish_file(
                component_results[
                    instrumental_recipe.recipe_id
                ].accompaniment_path,
                job_dir / "no_vocals.wav",
            )

        detail = (
            f"vocal={vocal_recipe.recipe_id}; "
            f"instrumental={instrumental_recipe.recipe_id}; "
            f"model_runs={len(unique_recipes)}"
        )
        save_separation_run(
            job_dir,
            recipe,
            source.name,
            postprocess_status="composed",
            postprocess_detail=detail,
        )
        result = SeparationResult(
            input_path=source,
            job_dir=job_dir,
            vocals_path=vocals_path,
            accompaniment_path=accompaniment_path,
            recipe=recipe,
        )
        logger.info("Custom separation complete: job_dir=%s %s", job_dir, detail)
        if progress_callback is not None:
            progress_callback(100)
        return result


def _component_progress_callback(
    progress_callback: ProgressCallback | None,
    *,
    index: int,
    count: int,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None
    count = max(1, count)

    def report(value: int) -> None:
        completed = index + max(0, min(100, value)) / 100
        progress_callback(min(96, round(completed * 96 / count)))

    return report
