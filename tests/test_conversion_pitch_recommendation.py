from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from jang_app.services.conversion_pitch_recommendation import (
    PitchRangeProfile,
    VocalPitchAnalysisCache,
    cached_model_analysis_is_current,
    precision_benchmark_pitch_profile,
    recommend_conversion_pitch,
)
from jang_app.services.model_dataset import ModelDatasetStore


class ConversionPitchRecommendationTests(unittest.TestCase):
    def test_recommends_only_pitch_that_fully_contains_equal_width_range(self) -> None:
        source = PitchRangeProfile(55.0, 60.0, 67.0, 100)
        model = PitchRangeProfile(50.0, 55.0, 62.0, 200)

        recommendation = recommend_conversion_pitch(source, model)

        self.assertEqual(recommendation.pitch, -5)
        self.assertEqual(recommendation.shifted_source_low_midi, 50.0)
        self.assertEqual(recommendation.shifted_source_high_midi, 62.0)
        self.assertEqual(recommendation.overlap_ratio, 1.0)
        self.assertEqual(recommendation.recommended_low_pitch, -5)
        self.assertEqual(recommendation.recommended_high_pitch, -5)
        self.assertTrue(recommendation.contains_pitch(-5))
        self.assertFalse(recommendation.is_large_shift)

    def test_recommends_wide_range_and_prefers_value_closest_to_zero(self) -> None:
        recommendation = recommend_conversion_pitch(
            PitchRangeProfile(55.0, 60.0, 67.0),
            PitchRangeProfile(48.0, 60.0, 72.0),
        )

        self.assertEqual(recommendation.recommended_low_pitch, -7)
        self.assertEqual(recommendation.recommended_high_pitch, 5)
        self.assertEqual(recommendation.pitch, 0)
        self.assertTrue(recommendation.contains_pitch(-3))
        self.assertFalse(recommendation.contains_pitch(6))

    def test_reports_best_overlap_when_source_is_wider_than_model(self) -> None:
        recommendation = recommend_conversion_pitch(
            PitchRangeProfile(48.0, 60.0, 72.0),
            PitchRangeProfile(54.0, 60.0, 66.0),
        )

        self.assertFalse(recommendation.has_recommended_range)
        self.assertEqual(recommendation.pitch, 0)
        self.assertLess(recommendation.overlap_ratio, 1.0)

    def test_marks_pitch_moves_beyond_one_octave_as_large(self) -> None:
        recommendation = recommend_conversion_pitch(
            PitchRangeProfile(67.0, 72.0, 77.0),
            PitchRangeProfile(48.0, 55.0, 62.0),
        )

        self.assertEqual(recommendation.pitch, -15)
        self.assertEqual(recommendation.recommended_low_pitch, -19)
        self.assertEqual(recommendation.recommended_high_pitch, -15)
        self.assertTrue(recommendation.is_large_shift)

    def test_precision_benchmark_range_becomes_absolute_model_notes(self) -> None:
        report = SimpleNamespace(
            recommended_low_shift=-24,
            recommended_high_shift=12,
            usable_low_shift=-24,
            usable_high_shift=13,
            best_shift_semitones=-6,
            points=(
                SimpleNamespace(shift_semitones=-24, successful_references=3),
                SimpleNamespace(shift_semitones=-6, successful_references=3),
                SimpleNamespace(shift_semitones=12, successful_references=2),
            ),
        )

        profile = precision_benchmark_pitch_profile(report)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.low_midi, 36.0)
        self.assertEqual(profile.center_midi, 54.0)
        self.assertEqual(profile.high_midi, 72.0)
        self.assertEqual(profile.sample_count, 8)

    def test_precision_benchmark_uses_usable_range_when_no_stable_range_exists(self) -> None:
        report = SimpleNamespace(
            recommended_low_shift=None,
            recommended_high_shift=None,
            usable_low_shift=-5,
            usable_high_shift=7,
            best_shift_semitones=None,
            points=(),
        )

        profile = precision_benchmark_pitch_profile(report)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(
            (profile.low_midi, profile.center_midi, profile.high_midi),
            (55.0, 61.0, 67.0),
        )

    def test_audio_analysis_cache_reuses_and_invalidates_a_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _tone(root / "vocal.wav", 220.0)
            cache = VocalPitchAnalysisCache(root / "cache")

            first = cache.get_or_analyze(source)
            second = cache.get_or_analyze(source)
            _tone(source, 440.0)
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            third = cache.get_or_analyze(source)

            self.assertEqual(first.generated_at, second.generated_at)
            self.assertAlmostEqual(first.profile.center_midi, 57.0, delta=0.8)
            self.assertAlmostEqual(third.profile.center_midi, 69.0, delta=0.8)
            self.assertNotEqual(first.source_mtime_ns, third.source_mtime_ns)

    def test_model_analysis_freshness_uses_dataset_manifest_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ModelDatasetStore(Path(temporary) / "workspace")
            model_root = store.root / "voice"
            analysis = model_root / "analysis" / "dataset-analysis.json"
            manifest = model_root / "dataset.json"
            analysis.parent.mkdir(parents=True)
            manifest.write_text("{}", encoding="utf-8")
            analysis.write_text("{}", encoding="utf-8")
            base = max(manifest.stat().st_mtime_ns, analysis.stat().st_mtime_ns)
            os.utime(manifest, ns=(base, base))
            os.utime(analysis, ns=(base + 1, base + 1))

            self.assertTrue(cached_model_analysis_is_current(store, "voice"))

            os.utime(manifest, ns=(base + 2_000_000_000, base + 2_000_000_000))
            self.assertFalse(cached_model_analysis_is_current(store, "voice"))


def _tone(path: Path, frequency: float) -> Path:
    sample_rate = 16_000
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    audio = 0.2 * np.sin(2 * np.pi * frequency * time)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")
    return path


if __name__ == "__main__":
    unittest.main()
