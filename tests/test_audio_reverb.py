from __future__ import annotations

import importlib
import unittest
from dataclasses import replace

import numpy as np

from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


class AudioReverbTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.audio_reverb = importlib.import_module("jang_app.services.audio_reverb")
        except ModuleNotFoundError:
            self.audio_reverb = None

    def test_zero_wet_reverb_preserves_the_dry_signal(self) -> None:
        self.assertIsNotNone(self.audio_reverb)
        source = np.linspace(-0.5, 0.5, 400, dtype=np.float32)[:, None]
        settings = StudioReverbSettings(dry_wet_percent=0)

        processed = self.audio_reverb.apply_reverb(source, 8_000, settings)

        self.assertEqual(processed.shape, source.shape)
        np.testing.assert_allclose(processed, source, atol=1e-6)

    def test_wet_reverb_is_deterministic_stereo_and_extends_the_tail(self) -> None:
        self.assertIsNotNone(self.audio_reverb)
        source = np.zeros((800, 1), dtype=np.float32)
        source[0, 0] = 0.5
        settings = StudioReverbSettings(
            decay_ms=400,
            dry_wet_percent=60,
            modulation_percent=15,
        )

        first = self.audio_reverb.apply_reverb(source, 8_000, settings)
        second = self.audio_reverb.apply_reverb(source, 8_000, settings)

        self.assertEqual(first.shape[1], 2)
        self.assertGreater(first.shape[0], source.shape[0])
        self.assertGreater(float(np.max(np.abs(first[source.shape[0] :]))), 0.0)
        self.assertTrue(np.isfinite(first).all())
        np.testing.assert_allclose(first, second, atol=1e-7)

    def test_distance_changes_only_early_reflections(self) -> None:
        settings = StudioReverbSettings(decay_ms=600, distance_m=1.0)

        near_early, near_late = self.audio_reverb._room_impulses(8_000, settings)
        far_early, far_late = self.audio_reverb._room_impulses(
            8_000,
            replace(settings, distance_m=8.0),
        )

        self.assertFalse(np.allclose(near_early, far_early))
        np.testing.assert_allclose(near_late, far_late, atol=1e-7)

    def test_modulation_changes_only_early_reflection_phase(self) -> None:
        settings = StudioReverbSettings(decay_ms=600, modulation_percent=0)

        still_early, still_late = self.audio_reverb._room_impulses(8_000, settings)
        moving_early, moving_late = self.audio_reverb._room_impulses(
            8_000,
            replace(settings, modulation_percent=70),
        )

        self.assertFalse(np.allclose(still_early, moving_early))
        np.testing.assert_allclose(still_late, moving_late, atol=1e-7)

    def test_brightness_extends_high_frequency_decay_without_moving_reflections(self) -> None:
        settings = StudioReverbSettings(decay_ms=900, brightness_percent=0)

        dark_early, dark_late = self.audio_reverb._room_impulses(8_000, settings)
        bright_early, bright_late = self.audio_reverb._room_impulses(
            8_000,
            replace(settings, brightness_percent=100),
        )

        np.testing.assert_allclose(dark_early, bright_early, atol=1e-7)
        tail_start = dark_late.shape[0] // 2
        dark_high = _band_energy(dark_late[tail_start:], 8_000, 2_000)
        bright_high = _band_energy(bright_late[tail_start:], 8_000, 2_000)
        self.assertGreater(bright_high, dark_high * 1.5)
        dark_retention = _high_frequency_retention(dark_late, 8_000)
        bright_retention = _high_frequency_retention(bright_late, 8_000)
        self.assertGreater(bright_retention, dark_retention * 5.0)

    def test_room_dimensions_rebuild_early_reflections_and_late_modes(self) -> None:
        settings = StudioReverbSettings(decay_ms=600, room_width_m=5.0)

        small_early, small_late = self.audio_reverb._room_impulses(8_000, settings)
        wide_early, wide_late = self.audio_reverb._room_impulses(
            8_000,
            replace(settings, room_width_m=12.0),
        )

        self.assertFalse(np.allclose(small_early, wide_early))
        self.assertFalse(np.allclose(small_late, wide_late))

    def test_negative_pre_delay_advances_the_first_reflection(self) -> None:
        settings = StudioReverbSettings(decay_ms=600, pre_delay_ms=80)

        delayed_early, _ = self.audio_reverb._room_impulses(8_000, settings)
        advanced_early, _ = self.audio_reverb._room_impulses(
            8_000,
            replace(settings, pre_delay_ms=-80),
        )

        self.assertLess(_first_nonzero_frame(advanced_early), _first_nonzero_frame(delayed_early))

    def test_mix_processing_applies_enabled_effects_before_pan(self) -> None:
        source = np.zeros((400, 1), dtype=np.float32)
        source[0, 0] = 0.25
        effect = StudioEffect(
            "fx-reverb",
            "reverb",
            reverb=StudioReverbSettings(decay_ms=300, dry_wet_percent=50),
        )

        processed = process_mix_source(
            source,
            8_000,
            effects=(effect,),
            pan_percent=100,
        )

        self.assertEqual(processed.shape[1], 2)
        self.assertGreater(processed.shape[0], source.shape[0])
        self.assertAlmostEqual(float(np.max(np.abs(processed[:, 0]))), 0.0, places=6)
        self.assertGreater(float(np.max(np.abs(processed[:, 1]))), 0.0)

    def test_disabled_effect_is_skipped(self) -> None:
        source = np.ones((32, 1), dtype=np.float32) * 0.1
        effect = StudioEffect("fx-reverb", "reverb", enabled=False)

        processed = process_mix_source(source, 8_000, effects=(effect,))

        np.testing.assert_allclose(processed, source, atol=1e-7)


def _band_energy(audio: np.ndarray, sample_rate: int, minimum_hz: float) -> float:
    spectrum = np.fft.rfft(audio, axis=0)
    frequencies = np.fft.rfftfreq(audio.shape[0], 1.0 / sample_rate)
    return float(np.sum(np.abs(spectrum[frequencies >= minimum_hz]) ** 2))


def _high_frequency_retention(audio: np.ndarray, sample_rate: int) -> float:
    quarter = max(2, audio.shape[0] // 4)
    early = audio[:quarter]
    late = audio[-quarter:]
    early_ratio = _band_ratio(early, sample_rate)
    late_ratio = _band_ratio(late, sample_rate)
    return late_ratio / max(early_ratio, 1e-12)


def _band_ratio(audio: np.ndarray, sample_rate: int) -> float:
    spectrum = np.fft.rfft(audio, axis=0)
    frequencies = np.fft.rfftfreq(audio.shape[0], 1.0 / sample_rate)
    high = float(np.sum(np.abs(spectrum[frequencies >= 2_000]) ** 2))
    low_band = (frequencies >= 100) & (frequencies < 1_000)
    low = float(np.sum(np.abs(spectrum[low_band]) ** 2))
    return high / max(low, 1e-12)


def _first_nonzero_frame(audio: np.ndarray) -> int:
    frames = np.flatnonzero(np.max(np.abs(audio), axis=1) > 1e-7)
    return int(frames[0]) if frames.size else audio.shape[0]


if __name__ == "__main__":
    unittest.main()
