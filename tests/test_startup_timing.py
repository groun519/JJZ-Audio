from __future__ import annotations

import unittest

from jang_app.services.startup_timing import StartupTimeline


class StartupTimelineTests(unittest.TestCase):
    def test_records_cumulative_elapsed_time_and_formats_summary(self) -> None:
        readings = iter((10.025, 10.100))
        timeline = StartupTimeline(started_at=10.0, clock=lambda: next(readings))

        first = timeline.mark("settings_loaded")
        second = timeline.mark("window_shown")

        self.assertAlmostEqual(first.elapsed_ms, 25.0)
        self.assertAlmostEqual(second.elapsed_ms, 100.0)
        self.assertEqual(timeline.marks, (first, second))
        self.assertEqual(
            timeline.summary(),
            "Startup timing | settings_loaded=25.0ms | window_shown=100.0ms | total=100.0ms",
        )

    def test_rejects_empty_and_duplicate_mark_names(self) -> None:
        timeline = StartupTimeline(started_at=1.0, clock=lambda: 1.0)

        with self.assertRaisesRegex(ValueError, "required"):
            timeline.mark("  ")

        timeline.mark("entry_ready")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            timeline.mark("entry_ready")

    def test_summary_without_marks_is_explicit(self) -> None:
        timeline = StartupTimeline(started_at=1.0, clock=lambda: 1.0)

        self.assertEqual(timeline.summary(), "Startup timing | no marks")


if __name__ == "__main__":
    unittest.main()
