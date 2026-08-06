from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.model_dataset_analysis import (
    PitchHistogramBin,
    _correct_isolated_octave_errors,
    analyze_model_dataset,
    load_cached_model_dataset_analysis,
    midi_note_name,
    pitch_coverage_ranges,
    recommended_pitch_shift,
)


class ModelDatasetAnalysisTests(unittest.TestCase):
    def test_analyzes_pitch_quality_and_reuses_unchanged_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _tone(root / "voice.wav", 220.0, 2.0)
            store = ModelDatasetStore(root / "workspace")
            dataset = store.add_sources("voice", (source,))
            item = dataset.items[0]
            store.select_items("voice", (item.item_id,))
            store.mark_item_ready("voice", item.item_id)
            progress: list[int] = []

            first = analyze_model_dataset(store, "voice", progress=progress.append)
            second = analyze_model_dataset(store, "voice")

            self.assertEqual(first.asset_count, 1)
            self.assertEqual(first.cached_asset_count, 0)
            self.assertEqual(second.cached_asset_count, 1)
            self.assertGreaterEqual(first.duration_ms, 1900)
            self.assertGreater(first.active_ratio, 0.95)
            self.assertIsNotNone(first.pitch_median_midi)
            self.assertAlmostEqual(first.pitch_median_midi or 0, 57.0, delta=0.8)
            self.assertAlmostEqual(first.pitch_center_midi or 0, 57.0, delta=0.8)
            self.assertEqual(progress[0], 0)
            self.assertEqual(progress[-1], 100)
            self.assertTrue(first.pitch_histogram)
            self.assertEqual(len(first.pitch_coverage_ranges), 1)
            self.assertEqual(first.pitch_coverage_ranges[0].low_midi, 57)
            self.assertEqual(first.pitch_coverage_ranges[0].high_midi, 57)

    def test_changed_training_audio_invalidates_only_its_cache_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            dataset = store.add_sources(
                "voice",
                (
                    _tone(root / "first.wav", 220.0, 1.5),
                    _tone(root / "second.wav", 330.0, 1.5),
                ),
            )
            store.select_items("voice", tuple(item.item_id for item in dataset.items))
            first = analyze_model_dataset(store, "voice")
            changed = store.load("voice").training_items[0]
            _tone(changed.working_path, 440.0, 1.5)

            second = analyze_model_dataset(store, "voice")

            self.assertEqual(first.cached_asset_count, 0)
            self.assertEqual(second.cached_asset_count, 1)

    def test_detects_low_male_reference_pitch_with_longer_pitch_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _tone(root / "low-voice.wav", 82.4069, 2.0)
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("voice", (source,)).items[0]
            store.select_items("voice", (item.item_id,))

            report = analyze_model_dataset(store, "voice")

            self.assertAlmostEqual(report.pitch_center_midi or 0, 40.0, delta=0.8)

    def test_empty_training_set_reports_attention_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ModelDatasetStore(Path(temporary) / "workspace")

            report = analyze_model_dataset(store, "voice")
            cached = load_cached_model_dataset_analysis(store, "voice")

            self.assertEqual(report.asset_count, 0)
            self.assertEqual(report.attention_count, 1)
            self.assertEqual(report.issues[0].code, "no_training_audio")
            self.assertEqual(cached, report)

    def test_formats_midi_note_names(self) -> None:
        self.assertEqual(midi_note_name(69), "A4")
        self.assertEqual(midi_note_name(None), "-")

    def test_splits_disconnected_dense_pitch_regions(self) -> None:
        histogram = tuple(
            PitchHistogramBin(
                note,
                midi_note_name(note),
                100 if 40 <= note <= 55 else 30 if 68 <= note <= 81 else 1,
            )
            for note in range(40, 82)
        )

        ranges = pitch_coverage_ranges(histogram)

        self.assertEqual(
            tuple((item.low_midi, item.high_midi) for item in ranges),
            ((40, 55), (68, 81)),
        )
        self.assertGreater(ranges[0].sample_ratio, ranges[1].sample_ratio)

    def test_bridges_small_gaps_inside_a_dense_pitch_region(self) -> None:
        histogram = tuple(
            PitchHistogramBin(
                note,
                midi_note_name(note),
                30 if note not in {56, 57} else 0,
            )
            for note in range(52, 62)
        )

        ranges = pitch_coverage_ranges(histogram)

        self.assertEqual(
            tuple((item.low_midi, item.high_midi) for item in ranges),
            ((52, 61),),
        )

    def test_corrects_only_isolated_octave_errors(self) -> None:
        corrected = _correct_isolated_octave_errors((48.0, 48.1, 60.1, 48.2, 48.0))
        sustained = _correct_isolated_octave_errors(
            (48.0, 48.1, 60.0, 60.1, 60.2, 60.0, 60.1)
        )

        self.assertAlmostEqual(corrected[2], 48.1, delta=0.2)
        self.assertEqual(sustained[2:], (60.0, 60.1, 60.2, 60.0, 60.1))

    def test_recommends_rvc_pitch_from_source_to_model_center(self) -> None:
        self.assertEqual(recommended_pitch_shift(48.0, 53.0), -5)
        self.assertEqual(recommended_pitch_shift(60.0, 48.0), 12)


def _tone(path: Path, frequency: float, duration_seconds: float) -> Path:
    sample_rate = 16_000
    time = np.arange(round(sample_rate * duration_seconds), dtype=np.float64) / sample_rate
    audio = 0.2 * np.sin(2 * np.pi * frequency * time)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")
    return path


if __name__ == "__main__":
    unittest.main()
