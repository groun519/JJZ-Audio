from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.separation_recipe import (
    CUSTOM_RECIPE,
    EFFECT_REMOVAL_RECIPE,
    FAST_RECIPE,
    HIGH_QUALITY_RECIPE,
    MAXIMUM_RECIPE,
    SEPARATION_RUN_MANIFEST,
    VOCAL_MELBAND_RECIPE,
    custom_separation_recipe,
    load_separation_run,
    save_separation_run,
    separation_recipe,
)


class SeparationRecipeTests(unittest.TestCase):
    def test_run_manifest_round_trips_quality_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "htdemucs_ft" / "song"
            job_dir.mkdir(parents=True)

            manifest = save_separation_run(
                job_dir,
                HIGH_QUALITY_RECIPE,
                "song.wav",
                postprocess_status="applied",
                postprocess_detail="residual 0.01 -> 0.0",
            )
            run = load_separation_run(job_dir)

            self.assertEqual(manifest, job_dir / SEPARATION_RUN_MANIFEST)
            self.assertEqual(run.recipe, HIGH_QUALITY_RECIPE)
            self.assertEqual(run.source_name, "song.wav")
            self.assertEqual(run.postprocess_status, "applied")
            self.assertIn("residual", run.postprocess_detail)

    def test_legacy_result_infers_model_without_rewriting_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "htdemucs" / "song"
            job_dir.mkdir(parents=True)

            run = load_separation_run(job_dir)

            self.assertEqual(run.recipe.label, "Legacy")
            self.assertEqual(run.recipe.model, "htdemucs")
            self.assertFalse((job_dir / SEPARATION_RUN_MANIFEST).exists())

    def test_maximum_recipe_round_trips_ensemble_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "demucs-maximum-v1" / "song"
            job_dir.mkdir(parents=True)

            save_separation_run(job_dir, MAXIMUM_RECIPE, "song.wav")
            run = load_separation_run(job_dir)

            self.assertTrue(run.recipe.is_ensemble)
            self.assertEqual(run.recipe.models, ("htdemucs_ft", "htdemucs"))
            self.assertEqual(run.recipe.ensemble_weights, (0.5, 0.5))
            self.assertIn("htdemucs_ft + htdemucs", run.recipe.summary)

    def test_legacy_high_quality_recipe_id_keeps_its_original_settings(self) -> None:
        recipe = separation_recipe("demucs-high-quality-v1")

        self.assertEqual(recipe.engine, "demucs")
        self.assertEqual(recipe.model, "htdemucs_ft")
        self.assertEqual(recipe.shifts, 2)

    def test_vocal_melband_recipe_is_resolved_by_its_stable_id(self) -> None:
        self.assertEqual(
            separation_recipe("roformer-vocal-melband-v1"),
            VOCAL_MELBAND_RECIPE,
        )

    def test_effect_removal_recipe_round_trips_its_second_stage_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "effect-removal" / "song"
            job_dir.mkdir(parents=True)

            save_separation_run(job_dir, EFFECT_REMOVAL_RECIPE, "song.wav")
            run = load_separation_run(job_dir)

            self.assertEqual(run.recipe, EFFECT_REMOVAL_RECIPE)
            self.assertEqual(
                run.recipe.required_models,
                (
                    "MelBandRoformer.ckpt",
                    "deverb_bs_roformer_8_256dim_8depth.ckpt",
                ),
            )
            self.assertIn("->", run.recipe.summary)

    def test_custom_recipe_round_trips_both_component_choices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "custom" / "song"
            job_dir.mkdir(parents=True)
            recipe = custom_separation_recipe(
                VOCAL_MELBAND_RECIPE.recipe_id,
                FAST_RECIPE.recipe_id,
            )

            save_separation_run(job_dir, recipe, "song.wav")
            run = load_separation_run(job_dir)

            self.assertEqual(run.recipe, recipe)
            self.assertEqual(
                run.recipe.required_models,
                (VOCAL_MELBAND_RECIPE.model, FAST_RECIPE.model),
            )
            self.assertIn("Vocal MelBand", run.recipe.summary)
            self.assertIn("HTDemucs", run.recipe.summary)

    def test_custom_recipe_deduplicates_a_shared_component_model(self) -> None:
        recipe = custom_separation_recipe(
            VOCAL_MELBAND_RECIPE.recipe_id,
            VOCAL_MELBAND_RECIPE.recipe_id,
        )

        self.assertEqual(recipe.required_models, (VOCAL_MELBAND_RECIPE.model,))
        self.assertEqual(CUSTOM_RECIPE.engine, "composite")


if __name__ == "__main__":
    unittest.main()
