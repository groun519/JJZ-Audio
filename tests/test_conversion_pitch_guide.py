from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.conversion_pitch_guide import ConversionPitchGuide
from jang_app.services.conversion_pitch_recommendation import (
    PitchRangeProfile,
    PitchRecommendation,
)


class ConversionPitchGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_compact_recommendation_is_informational(self) -> None:
        guide = ConversionPitchGuide()

        guide.set_recommendation(_recommendation(-5), current_pitch=0)

        self.assertFalse(guide.details.isVisible())
        self.assertIn("-5", guide.status_label.text())
        guide.close()

    def test_current_pitch_marker_updates_when_pitch_changes(self) -> None:
        guide = ConversionPitchGuide()
        guide.set_recommendation(_recommendation(3, low=1, high=4), current_pitch=3)
        matching_text = guide.status_label.text()

        guide.set_current_pitch(5)
        self.assertNotEqual(guide.status_label.text(), matching_text)
        self.assertEqual(guide.range_view._current_pitch, 5)
        guide.close()

    def test_recommended_range_is_shown_instead_of_a_single_pitch(self) -> None:
        guide = ConversionPitchGuide()

        guide.set_recommendation(_recommendation(0, low=-7, high=5), current_pitch=0)

        self.assertIn("-7 ~ +5", guide.status_label.text())
        self.assertTrue(
            "음역 적합" in guide.status_label.text()
            or "In range" in guide.status_label.text()
        )
        guide.close()

    def test_details_expand_only_for_a_ready_recommendation(self) -> None:
        guide = ConversionPitchGuide()
        guide.set_analyzing()
        self.assertFalse(guide.toggle_button.isVisible())

        guide.set_recommendation(_recommendation(-2), current_pitch=0)
        guide.toggle_button.click()

        self.assertTrue(guide.is_expanded())
        self.assertFalse(guide.details.isHidden())
        guide.close()


def _recommendation(
    pitch: int,
    *,
    low: int | None = None,
    high: int | None = None,
) -> PitchRecommendation:
    return PitchRecommendation(
        source=PitchRangeProfile(55.0, 60.0, 67.0, 120),
        model=PitchRangeProfile(50.0, 55.0, 62.0, 200),
        pitch=pitch,
        overlap_ratio=1.0,
        is_large_shift=abs(pitch) > 12,
        recommended_low_pitch=low if low is not None else pitch,
        recommended_high_pitch=high if high is not None else pitch,
    )


if __name__ == "__main__":
    unittest.main()
