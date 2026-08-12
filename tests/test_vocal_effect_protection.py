from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.vocal_effect_protection import (
    VocalEffectProtectionError,
    protect_effect_removed_vocals,
)


class VocalEffectProtectionTests(unittest.TestCase):
    def test_restores_only_a_local_vocal_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wet = root / "wet.wav"
            dry = root / "dry.wav"
            output = root / "protected.wav"
            sample_rate = 1_000
            time = np.arange(2_000, dtype=np.float32) / sample_rate
            wet_audio = (0.4 * np.sin(2 * np.pi * 80 * time))[:, None]
            wet_audio = np.repeat(wet_audio, 2, axis=1)
            dry_audio = wet_audio * 0.9
            dry_audio[700:1_100] = 0.0
            sf.write(wet, wet_audio, sample_rate, subtype="FLOAT")
            sf.write(dry, dry_audio, sample_rate, subtype="FLOAT")

            report = protect_effect_removed_vocals(wet, dry, output)
            protected, _ = sf.read(output, dtype="float32", always_2d=True)

            self.assertGreater(_rms(protected[800:1_000]), 0.20)
            np.testing.assert_allclose(protected[:500], dry_audio[:500], atol=1e-5)
            self.assertGreater(report.protected_windows, 0)
            self.assertGreater(report.severe_collapse_windows, 0)
            self.assertLessEqual(report.maximum_restore_blend, 0.9)
            self.assertGreater(report.maximum_dry_gain, 1.0)

    def test_leaves_normal_effect_reduction_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wet = root / "wet.wav"
            dry = root / "dry.wav"
            output = root / "protected.wav"
            wet_audio = np.full((1_000, 2), 0.2, dtype=np.float32)
            dry_audio = wet_audio * 0.8
            sf.write(wet, wet_audio, 1_000, subtype="FLOAT")
            sf.write(dry, dry_audio, 1_000, subtype="FLOAT")

            report = protect_effect_removed_vocals(wet, dry, output)
            protected, _ = sf.read(output, dtype="float32", always_2d=True)

            np.testing.assert_allclose(protected, dry_audio, atol=1e-7)
            self.assertEqual(report.protected_windows, 0)

    def test_does_not_restore_low_level_ambience(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wet = root / "wet.wav"
            dry = root / "dry.wav"
            output = root / "protected.wav"
            wet_audio = np.full((1_000, 2), 0.002, dtype=np.float32)
            dry_audio = np.zeros_like(wet_audio)
            sf.write(wet, wet_audio, 1_000, subtype="FLOAT")
            sf.write(dry, dry_audio, 1_000, subtype="FLOAT")

            report = protect_effect_removed_vocals(wet, dry, output)
            protected, _ = sf.read(output, dtype="float32", always_2d=True)

            np.testing.assert_allclose(protected, dry_audio, atol=1e-7)
            self.assertEqual(report.protected_windows, 0)

    def test_rejects_misaligned_stems_without_replacing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wet = root / "wet.wav"
            dry = root / "dry.wav"
            output = root / "protected.wav"
            sf.write(wet, np.zeros((100, 2), dtype=np.float32), 1_000)
            sf.write(dry, np.zeros((99, 2), dtype=np.float32), 1_000)
            output.write_bytes(b"existing")

            with self.assertRaisesRegex(VocalEffectProtectionError, "not aligned"):
                protect_effect_removed_vocals(wet, dry, output)

            self.assertEqual(output.read_bytes(), b"existing")


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


if __name__ == "__main__":
    unittest.main()
