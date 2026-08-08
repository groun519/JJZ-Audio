from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.separation_postprocess import (
    SeparationPostprocessError,
    enforce_mixture_consistency,
)


class SeparationPostprocessTests(unittest.TestCase):
    def test_corrected_stems_sum_to_the_source_without_changing_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            vocals = root / "vocals.wav"
            instrumental = root / "no_vocals.wav"
            frames = 4096
            time = np.linspace(0, 1, frames, endpoint=False, dtype=np.float32)
            voice = np.column_stack((np.sin(time * 70), np.sin(time * 70))) * 0.2
            backing = np.column_stack((np.cos(time * 45), np.cos(time * 45))) * 0.3
            mixture = voice + backing
            sf.write(source, mixture, 44_100, subtype="FLOAT")
            sf.write(vocals, voice - 0.01, 44_100, subtype="FLOAT")
            sf.write(instrumental, backing - 0.01, 44_100, subtype="FLOAT")

            report = enforce_mixture_consistency(source, vocals, instrumental)
            corrected_voice, rate = sf.read(vocals, dtype="float32", always_2d=True)
            corrected_backing, _ = sf.read(instrumental, dtype="float32", always_2d=True)

            self.assertEqual(rate, 44_100)
            self.assertEqual(corrected_voice.shape, mixture.shape)
            np.testing.assert_allclose(corrected_voice + corrected_backing, mixture, atol=1e-6)
            self.assertGreater(report.residual_rms_before, report.residual_rms_after)
            self.assertLess(report.residual_rms_after, 1e-6)

    def test_mismatched_stem_shape_is_rejected_before_replacing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            vocals = root / "vocals.wav"
            instrumental = root / "no_vocals.wav"
            sf.write(source, np.zeros((100, 2), dtype=np.float32), 44_100)
            sf.write(vocals, np.zeros((100, 2), dtype=np.float32), 44_100)
            sf.write(instrumental, np.zeros((99, 2), dtype=np.float32), 44_100)

            with self.assertRaisesRegex(SeparationPostprocessError, "Cannot align"):
                enforce_mixture_consistency(source, vocals, instrumental)


if __name__ == "__main__":
    unittest.main()
