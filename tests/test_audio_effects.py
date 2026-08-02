from __future__ import annotations

import unittest

import numpy as np

from jang_app.services.audio_effects import MasterProcessing, process_master_audio


class AudioEffectsTests(unittest.TestCase):
    def test_master_gain_is_applied_without_mutating_the_source(self) -> None:
        source = np.full((4, 2), 0.5, dtype=np.float32)

        processed = process_master_audio(source, MasterProcessing(gain_db=-6))

        self.assertTrue(np.allclose(processed, 0.2506, atol=0.001))
        self.assertTrue(np.all(source == 0.5))

    def test_stereo_width_uses_mid_side_processing(self) -> None:
        source = np.array([[0.75, 0.25]], dtype=np.float32)

        mono = process_master_audio(source, MasterProcessing(stereo_width_percent=0))
        wide = process_master_audio(source, MasterProcessing(stereo_width_percent=200))

        self.assertTrue(np.allclose(mono, [[0.5, 0.5]]))
        self.assertTrue(np.allclose(wide, [[1.0, 0.0]]))

    def test_out_of_range_processing_values_are_clamped(self) -> None:
        source = np.array([[0.25]], dtype=np.float32)
        processed = process_master_audio(source, MasterProcessing(gain_db=999, stereo_width_percent=-20))
        self.assertAlmostEqual(float(processed[0, 0]), 0.25 * 10 ** (12 / 20), places=5)


if __name__ == "__main__":
    unittest.main()
