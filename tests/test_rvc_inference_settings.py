from __future__ import annotations

import unittest

from jang_app.services.rvc_inference_settings import (
    PRESET_BALANCED,
    PRESET_CUSTOM,
    PRESET_DETAIL,
    PRESET_TIMBRE,
    RvcInferenceSettings,
    matching_rvc_inference_preset,
    normalize_rvc_inference_settings,
    rvc_inference_preset,
    rvc_inference_settings_from_data,
)


class RvcInferenceSettingsTests(unittest.TestCase):
    def test_presets_provide_distinct_quality_starting_points(self) -> None:
        balanced = rvc_inference_preset(PRESET_BALANCED)
        timbre = rvc_inference_preset(PRESET_TIMBRE)
        detail = rvc_inference_preset(PRESET_DETAIL)

        self.assertEqual(balanced, RvcInferenceSettings())
        self.assertGreater(timbre.index_rate, balanced.index_rate)
        self.assertLess(detail.index_rate, balanced.index_rate)
        self.assertLess(detail.protect, balanced.protect)

    def test_matching_preset_marks_modified_values_as_custom(self) -> None:
        self.assertEqual(
            matching_rvc_inference_preset(RvcInferenceSettings(index_rate=0.80)),
            PRESET_CUSTOM,
        )

    def test_loaded_values_are_clamped_to_runtime_ranges(self) -> None:
        settings = rvc_inference_settings_from_data(
            {
                "index_rate": 4,
                "filter_radius": -3,
                "rms_mix_rate": "0.4",
                "protect": 2,
            }
        )

        self.assertEqual(
            settings,
            RvcInferenceSettings(
                index_rate=1.0,
                filter_radius=0,
                rms_mix_rate=0.4,
                protect=0.5,
            ),
        )

    def test_normalization_rounds_serialized_float_noise(self) -> None:
        settings = normalize_rvc_inference_settings(
            RvcInferenceSettings(index_rate=0.749999, rms_mix_rate=0.251)
        )

        self.assertEqual(settings.index_rate, 0.75)
        self.assertEqual(settings.rms_mix_rate, 0.25)


if __name__ == "__main__":
    unittest.main()
