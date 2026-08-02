from __future__ import annotations

import unittest

from jang_app.services.segment_review import (
    SEGMENT_HELD,
    SEGMENT_PENDING,
    build_segment_candidates,
    split_review_regions,
    update_candidate_status,
)


class SegmentReviewTests(unittest.TestCase):
    def test_long_regions_are_split_into_balanced_review_segments(self) -> None:
        segments = split_review_regions(((1000, 32000),), max_duration_ms=12000)

        self.assertEqual(segments[0][0], 1000)
        self.assertEqual(segments[-1][1], 32000)
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(end - start <= 12000 for start, end in segments))

    def test_existing_candidate_state_survives_reanalysis(self) -> None:
        initial = build_segment_candidates(((100, 900), (1200, 2200)))
        held = update_candidate_status(initial, initial[0].candidate_id, SEGMENT_HELD)

        rebuilt = build_segment_candidates(((100, 900), (1200, 2200), (2500, 3000)), held)

        self.assertEqual(rebuilt[0].candidate_id, initial[0].candidate_id)
        self.assertEqual(rebuilt[0].status, SEGMENT_HELD)
        self.assertEqual(rebuilt[2].status, SEGMENT_PENDING)


if __name__ == "__main__":
    unittest.main()
