from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.separation_recipe import (
    HIGH_QUALITY_RECIPE,
    MAXIMUM_RECIPE,
    SEPARATION_RUN_MANIFEST,
    load_separation_run,
    save_separation_run,
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


if __name__ == "__main__":
    unittest.main()
