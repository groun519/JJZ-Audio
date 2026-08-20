from __future__ import annotations

import unittest

from jang_app.services.video_quality_optimizer import (
    VideoSampleWindow,
    adaptive_resolution_candidates,
    best_scored_resolution,
    parse_ssim_score,
    parse_vmaf_score,
    representative_video_windows,
)


class VideoQualityOptimizerTests(unittest.TestCase):
    def test_short_video_uses_the_complete_timeline_as_one_sample(self) -> None:
        self.assertEqual(
            representative_video_windows(12_000),
            (VideoSampleWindow(0, 12_000),),
        )

    def test_long_video_samples_the_front_middle_and_end(self) -> None:
        windows = representative_video_windows(180_000)

        self.assertEqual(len(windows), 3)
        self.assertTrue(all(window.duration_ms == 6_000 for window in windows))
        self.assertLess(windows[0].start_ms, windows[1].start_ms)
        self.assertLess(windows[1].start_ms, windows[2].start_ms)

    def test_candidates_respect_export_and_native_pixel_ceilings(self) -> None:
        self.assertEqual(
            adaptive_resolution_candidates((1920, 1080)),
            ((1920, 1080), (1706, 960), (1280, 720), (854, 480)),
        )
        self.assertEqual(
            adaptive_resolution_candidates(
                (1920, 1080),
                source_pixel_ceiling=1280 * 720,
            ),
            ((1280, 720), (854, 480)),
        )

    def test_quality_score_parsers_read_ffmpeg_summaries(self) -> None:
        self.assertEqual(parse_vmaf_score("VMAF score: 94.125000"), 94.125)
        self.assertAlmostEqual(parse_ssim_score("All:0.987654 (19.2)"), 98.7654)

    def test_highest_objective_score_wins_regardless_of_resolution(self) -> None:
        self.assertEqual(
            best_scored_resolution(
                {
                    (1920, 1080): 82.0,
                    (1706, 960): 91.5,
                    (1280, 720): 95.0,
                    (854, 480): 89.0,
                }
            ),
            (1280, 720),
        )


if __name__ == "__main__":
    unittest.main()
