from __future__ import annotations

import unittest

from jang_app.services.studio_audio_levels import (
    STUDIO_SOURCE_VOLUME_MAX,
    studio_source_gain,
)


class StudioAudioLevelTests(unittest.TestCase):
    def test_source_gain_combines_track_volume_and_clip_db(self) -> None:
        self.assertAlmostEqual(studio_source_gain(100, 0), 1.0)
        self.assertAlmostEqual(studio_source_gain(150, 0), 1.5)
        self.assertAlmostEqual(studio_source_gain(100, -6), 0.501187, places=5)

    def test_source_gain_clamps_to_supported_mix_range(self) -> None:
        self.assertEqual(studio_source_gain(-50, 0), 0.0)
        self.assertEqual(studio_source_gain(500, 100), STUDIO_SOURCE_VOLUME_MAX)


if __name__ == "__main__":
    unittest.main()
