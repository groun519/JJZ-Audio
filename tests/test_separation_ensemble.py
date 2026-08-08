from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.pipeline.demucs_ensemble_engine import DemucsEnsembleEngine
from jang_app.pipeline import separate as separate_pipeline
from jang_app.pipeline.separation_engine import SeparationRequest, SeparationResult
from jang_app.services.separation_ensemble import (
    SeparationEnsembleError,
    SeparationStemPair,
    blend_stem_pairs,
)
from jang_app.services.separation_recipe import MAXIMUM_RECIPE, load_separation_run


class SeparationEnsembleTests(unittest.TestCase):
    def test_weighted_blend_preserves_float_shape_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _stem_pair(root / "first", 0.2, 0.3, frames=4096)
            second = _stem_pair(root / "second", 0.4, 0.1, frames=4096)
            output = root / "result"

            report = blend_stem_pairs(
                (first, second),
                output / "vocals.wav",
                output / "no_vocals.wav",
                weights=(0.25, 0.75),
            )
            vocals, rate = sf.read(output / "vocals.wav", dtype="float32", always_2d=True)
            instrumental, _ = sf.read(
                output / "no_vocals.wav",
                dtype="float32",
                always_2d=True,
            )

            self.assertEqual(report.members, 2)
            self.assertEqual(rate, 44_100)
            self.assertEqual(vocals.shape, (4096, 2))
            np.testing.assert_allclose(vocals, 0.35, atol=1e-6)
            np.testing.assert_allclose(instrumental, 0.15, atol=1e-6)

    def test_mismatched_member_shape_is_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _stem_pair(root / "first", 0.2, 0.3, frames=100)
            second = _stem_pair(root / "second", 0.4, 0.1, frames=99)
            output = root / "result"

            with self.assertRaisesRegex(SeparationEnsembleError, "same sample rate"):
                blend_stem_pairs(
                    (first, second),
                    output / "vocals.wav",
                    output / "no_vocals.wav",
                )

            self.assertFalse((output / "vocals.wav").exists())
            self.assertFalse((output / "no_vocals.wav").exists())

    def test_engine_runs_members_sequentially_and_keeps_only_final_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            sf.write(source, np.full((2048, 2), 0.5, dtype=np.float32), 44_100, subtype="FLOAT")
            component = _FakeComponentEngine()
            progress: list[int] = []

            result = DemucsEnsembleEngine(component).separate(
                SeparationRequest(source, root / "output", MAXIMUM_RECIPE),
                progress.append,
            )

            self.assertEqual(component.models, ["htdemucs_ft", "htdemucs"])
            self.assertEqual(progress[-1], 100)
            self.assertEqual(progress, sorted(progress))
            self.assertEqual(len(progress), len(set(progress)))
            self.assertFalse((root / "output" / ".e").exists())
            self.assertTrue(result.vocals_path.is_file())
            self.assertTrue(result.accompaniment_path.is_file())
            self.assertEqual(load_separation_run(result.job_dir).recipe, MAXIMUM_RECIPE)
            vocals, _ = sf.read(result.vocals_path, dtype="float32", always_2d=True)
            instrumental, _ = sf.read(
                result.accompaniment_path,
                dtype="float32",
                always_2d=True,
            )
            np.testing.assert_allclose(vocals, 0.3, atol=1e-6)
            np.testing.assert_allclose(instrumental, 0.2, atol=1e-6)

    def test_public_pipeline_selects_ensemble_engine_for_maximum_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            sf.write(source, np.full((128, 2), 0.5, dtype=np.float32), 44_100)
            selected_engine = _FakeComponentEngine()
            with patch.object(
                separate_pipeline,
                "DemucsEnsembleEngine",
                return_value=selected_engine,
            ) as engine_factory:
                result = separate_pipeline.separate_audio(
                    source,
                    root / "output",
                    recipe=MAXIMUM_RECIPE,
                )

            engine_factory.assert_called_once_with()
            self.assertEqual(result.recipe, MAXIMUM_RECIPE)


class _FakeComponentEngine:
    engine_id = "demucs"

    def __init__(self) -> None:
        self.models: list[str] = []

    def separate(self, request, progress_callback=None) -> SeparationResult:
        self.models.append(request.recipe.model)
        if progress_callback is not None:
            progress_callback(20)
            progress_callback(100)
        values = {
            "htdemucs_ft": (0.2, 0.3),
            "htdemucs": (0.4, 0.1),
        }
        vocal, instrumental = values[request.recipe.model]
        pair = _stem_pair(
            request.output_root / request.recipe.model / request.input_path.stem,
            vocal,
            instrumental,
            frames=2048,
        )
        return SeparationResult(
            input_path=request.input_path,
            job_dir=pair.vocals_path.parent,
            vocals_path=pair.vocals_path,
            accompaniment_path=pair.instrumental_path,
            recipe=request.recipe,
        )


def _stem_pair(
    root: Path,
    vocal_value: float,
    instrumental_value: float,
    *,
    frames: int,
) -> SeparationStemPair:
    root.mkdir(parents=True, exist_ok=True)
    vocals = root / "vocals.wav"
    instrumental = root / "no_vocals.wav"
    sf.write(
        vocals,
        np.full((frames, 2), vocal_value, dtype=np.float32),
        44_100,
        subtype="FLOAT",
    )
    sf.write(
        instrumental,
        np.full((frames, 2), instrumental_value, dtype=np.float32),
        44_100,
        subtype="FLOAT",
    )
    return SeparationStemPair(vocals, instrumental)


if __name__ == "__main__":
    unittest.main()
