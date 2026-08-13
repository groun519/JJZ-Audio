from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from jang_app.pipeline.quick_production import (
    reusable_fast_separation,
    run_quick_production,
)
from jang_app.pipeline.rvc_convert import RvcConversionResult
from jang_app.pipeline.separation_engine import SeparationResult
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.separation_recipe import FAST_RECIPE, PRECISION_RECIPE
from jang_app.services.settings import RvcSettings
from jang_app.services.song_library import SongVocalVersion


class QuickProductionTests(unittest.TestCase):
    def test_reusable_fast_separation_selects_the_latest_complete_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            older = _version(root / "older", FAST_RECIPE.recipe_id, "2026-08-01")
            newer = _version(root / "newer", FAST_RECIPE.recipe_id, "2026-08-03")
            _version(root / "precision", PRECISION_RECIPE.recipe_id, "2026-08-04")
            incomplete = _version(root / "incomplete", FAST_RECIPE.recipe_id, "2026-08-05")
            incomplete.instrumental_path.unlink()

            selected = reusable_fast_separation((older, incomplete, newer))

            self.assertIs(selected, newer)

    def test_reuses_fast_separation_and_runs_only_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_dir = root / "fast"
            sound_set = _sound_set(job_dir)
            settings = RvcSettings(root=root, voice_model="voice.pth")
            progress: list[int] = []
            conversion = _conversion(job_dir)

            with (
                patch("jang_app.pipeline.quick_production.separate_audio") as separate,
                patch(
                    "jang_app.pipeline.quick_production.convert_vocal_with_rvc",
                    side_effect=lambda _source, _output, _settings, callback: (
                        callback(0),
                        callback(100),
                        conversion,
                    )[-1],
                ) as convert,
            ):
                result = run_quick_production(
                    source_path=None,
                    separation_output_root=None,
                    reusable_sound_set=sound_set,
                    rvc_settings=settings,
                    progress_callback=progress.append,
                )

            separate.assert_not_called()
            convert.assert_called_once_with(
                sound_set.vocals_path,
                sound_set.job_dir,
                settings,
                ANY,
            )
            self.assertTrue(result.reused_separation)
            self.assertEqual(result.sound_set, sound_set)
            self.assertEqual(progress[0], 45)
            self.assertEqual(progress[-1], 100)

    def test_runs_fast_separation_then_balanced_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"audio")
            job_dir = root / "run"
            separation = _separation(source, job_dir)
            conversion = _conversion(job_dir)
            settings = RvcSettings(root=root, voice_model="voice.pth")
            progress: list[int] = []

            def separate_side_effect(
                input_path: Path,
                *,
                output_root: Path,
                recipe: object,
                progress_callback: object,
            ) -> SeparationResult:
                self.assertEqual(input_path, source)
                self.assertEqual(output_root, job_dir)
                self.assertIs(recipe, FAST_RECIPE)
                progress_callback(0)
                progress_callback(100)
                return separation

            def convert_side_effect(
                input_path: Path,
                output_dir: Path,
                actual_settings: RvcSettings,
                progress_callback: object,
            ) -> RvcConversionResult:
                self.assertEqual(input_path, separation.vocals_path)
                self.assertEqual(output_dir, job_dir)
                self.assertIs(actual_settings, settings)
                progress_callback(0)
                progress_callback(100)
                return conversion

            with (
                patch(
                    "jang_app.pipeline.quick_production.separate_audio",
                    side_effect=separate_side_effect,
                ),
                patch(
                    "jang_app.pipeline.quick_production.convert_vocal_with_rvc",
                    side_effect=convert_side_effect,
                ),
            ):
                result = run_quick_production(
                    source_path=source,
                    separation_output_root=job_dir,
                    reusable_sound_set=None,
                    rvc_settings=settings,
                    progress_callback=progress.append,
                )

            self.assertFalse(result.reused_separation)
            self.assertIs(result.separation, separation)
            self.assertEqual(result.sound_set.job_dir, job_dir)
            self.assertEqual(progress[0], 0)
            self.assertIn(45, progress)
            self.assertEqual(progress[-1], 100)
            self.assertEqual(progress, sorted(progress))


def _version(root: Path, recipe_id: str, added_at: str) -> SongVocalVersion:
    root.mkdir(parents=True)
    vocals = root / "vocals.wav"
    instrumental = root / "no_vocals.wav"
    vocals.write_bytes(b"vocals")
    instrumental.write_bytes(b"instrumental")
    return SongVocalVersion(
        version_id=root.name,
        label=root.name,
        job_dir=root,
        added_at=added_at,
        vocals_path=vocals,
        instrumental_path=instrumental,
        converted_vocal_paths=(),
        separation_recipe_id=recipe_id,
    )


def _sound_set(job_dir: Path) -> OutputSoundSet:
    job_dir.mkdir(parents=True)
    vocals = job_dir / "vocals.wav"
    instrumental = job_dir / "no_vocals.wav"
    vocals.write_bytes(b"vocals")
    instrumental.write_bytes(b"instrumental")
    return OutputSoundSet("Fast Separation", job_dir, vocals, instrumental, ())


def _separation(source: Path, job_dir: Path) -> SeparationResult:
    sound_set = _sound_set(job_dir)
    return SeparationResult(
        source,
        job_dir,
        sound_set.vocals_path,
        sound_set.instrumental_path,
        FAST_RECIPE,
    )


def _conversion(job_dir: Path) -> RvcConversionResult:
    return RvcConversionResult(
        input_path=job_dir / "vocals.wav",
        output_path=job_dir / "vocals_rvc.wav",
        voice_model_path=job_dir / "voice.pth",
        index_path=None,
    )


if __name__ == "__main__":
    unittest.main()
