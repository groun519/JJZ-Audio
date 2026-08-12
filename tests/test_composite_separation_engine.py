from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.pipeline.composite_separation_engine import CompositeSeparationEngine
from jang_app.pipeline.separation_engine import SeparationRequest, SeparationResult
from jang_app.services.separation_recipe import (
    FAST_RECIPE,
    VOCAL_MELBAND_RECIPE,
    custom_separation_recipe,
    load_separation_run,
)


class CompositeSeparationEngineTests(unittest.TestCase):
    def test_combines_the_selected_stem_from_each_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"source")
            calls: list[str] = []
            engine = CompositeSeparationEngine(_fake_factory(calls))
            recipe = custom_separation_recipe(
                VOCAL_MELBAND_RECIPE.recipe_id,
                FAST_RECIPE.recipe_id,
            )

            with patch(
                "jang_app.pipeline.composite_separation_engine.TOOL_WORKSPACE_DIR",
                root / "tools",
            ):
                result = engine.separate(
                    SeparationRequest(source, root / "result", recipe)
                )

            self.assertEqual(
                calls,
                [VOCAL_MELBAND_RECIPE.recipe_id, FAST_RECIPE.recipe_id],
            )
            self.assertEqual(
                result.vocals_path.read_text(encoding="utf-8"),
                f"vocal:{VOCAL_MELBAND_RECIPE.recipe_id}",
            )
            self.assertEqual(
                result.accompaniment_path.read_text(encoding="utf-8"),
                f"instrumental:{FAST_RECIPE.recipe_id}",
            )
            run = load_separation_run(result.job_dir)
            self.assertEqual(run.recipe, recipe)
            self.assertEqual(run.postprocess_status, "composed")
            self.assertIn("model_runs=2", run.postprocess_detail)

    def test_runs_a_shared_model_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"source")
            calls: list[str] = []
            recipe = custom_separation_recipe(
                FAST_RECIPE.recipe_id,
                FAST_RECIPE.recipe_id,
            )

            with patch(
                "jang_app.pipeline.composite_separation_engine.TOOL_WORKSPACE_DIR",
                root / "tools",
            ):
                CompositeSeparationEngine(_fake_factory(calls)).separate(
                    SeparationRequest(source, root / "result", recipe)
                )

            self.assertEqual(calls, [FAST_RECIPE.recipe_id])


class _FakeEngine:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def separate(self, request, progress_callback=None) -> SeparationResult:
        recipe = request.recipe
        self._calls.append(recipe.recipe_id)
        request.output_root.mkdir(parents=True, exist_ok=True)
        vocals = request.output_root / "vocals.wav"
        instrumental = request.output_root / "no_vocals.wav"
        vocals.write_text(f"vocal:{recipe.recipe_id}", encoding="utf-8")
        instrumental.write_text(
            f"instrumental:{recipe.recipe_id}", encoding="utf-8"
        )
        if progress_callback is not None:
            progress_callback(100)
        return SeparationResult(
            input_path=request.input_path,
            job_dir=request.output_root,
            vocals_path=vocals,
            accompaniment_path=instrumental,
            recipe=recipe,
        )


def _fake_factory(calls: list[str]):
    def factory(recipe):
        engine = _FakeEngine(calls)
        engine.engine_id = recipe.engine
        return engine

    return factory


if __name__ == "__main__":
    unittest.main()
