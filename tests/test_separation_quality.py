from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.separation_quality import measure_separation_quality


class SeparationQualityTests(unittest.TestCase):
    def test_reference_matching_estimate_scores_above_leaky_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            time = np.linspace(0, 1, 8000, endpoint=False, dtype=np.float32)
            vocals = np.sin(time * 300).reshape(-1, 1) * 0.3
            instrumental = np.cos(time * 113).reshape(-1, 1) * 0.2
            reference_vocals = _write(root / "reference-vocals.wav", vocals)
            reference_instrumental = _write(root / "reference-instrumental.wav", instrumental)
            clean_vocals = _write(root / "clean-vocals.wav", vocals)
            clean_instrumental = _write(root / "clean-instrumental.wav", instrumental)
            leaky_vocals = _write(root / "leaky-vocals.wav", vocals + instrumental * 0.5)
            leaky_instrumental = _write(root / "leaky-instrumental.wav", instrumental + vocals * 0.5)

            clean = measure_separation_quality(
                reference_vocals,
                reference_instrumental,
                clean_vocals,
                clean_instrumental,
            )
            leaky = measure_separation_quality(
                reference_vocals,
                reference_instrumental,
                leaky_vocals,
                leaky_instrumental,
            )

            self.assertGreater(clean.mean_si_sdr_db, leaky.mean_si_sdr_db)
            self.assertLess(clean.mixture_residual_rms, 1e-6)


def _write(path: Path, audio: np.ndarray) -> Path:
    sf.write(path, audio, 8000, subtype="FLOAT")
    return path


if __name__ == "__main__":
    unittest.main()
