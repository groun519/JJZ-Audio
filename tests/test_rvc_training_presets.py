from __future__ import annotations

import unittest

from jang_app.services.rvc_training_presets import (
    RvcTrainingPresetId,
    recommend_rvc_training_settings,
)


class RvcTrainingPresetTests(unittest.TestCase):
    def test_quick_preset_preserves_existing_training_defaults(self) -> None:
        recommendation = recommend_rvc_training_settings(
            RvcTrainingPresetId.QUICK,
            accelerated=True,
        )

        self.assertEqual(recommendation.target_epoch, 20)
        self.assertEqual(recommendation.batch_size, 4)
        self.assertEqual(recommendation.checkpoint_interval, 5)

    def test_resume_recommendation_adds_epochs_to_current_checkpoint(self) -> None:
        recommendation = recommend_rvc_training_settings(
            RvcTrainingPresetId.STANDARD,
            current_epoch=120,
            accelerated=True,
        )

        self.assertEqual(recommendation.target_epoch, 320)
        self.assertEqual(recommendation.checkpoint_interval, 20)

    def test_cpu_recommendation_uses_a_conservative_batch(self) -> None:
        recommendation = recommend_rvc_training_settings(
            RvcTrainingPresetId.HIGH_QUALITY,
            accelerated=False,
        )

        self.assertEqual(recommendation.target_epoch, 300)
        self.assertEqual(recommendation.batch_size, 2)

    def test_low_memory_gpu_uses_a_safe_batch(self) -> None:
        recommendation = recommend_rvc_training_settings(
            RvcTrainingPresetId.STANDARD,
            accelerated=True,
            adapter_memory_bytes=4 * 1024**3,
        )

        self.assertEqual(recommendation.batch_size, 2)

    def test_high_memory_gpu_can_use_a_larger_batch(self) -> None:
        recommendation = recommend_rvc_training_settings(
            RvcTrainingPresetId.STANDARD,
            accelerated=True,
            adapter_memory_bytes=12 * 1024**3,
        )

        self.assertEqual(recommendation.batch_size, 6)

    def test_custom_settings_have_no_fixed_recommendation(self) -> None:
        with self.assertRaises(ValueError):
            recommend_rvc_training_settings(RvcTrainingPresetId.CUSTOM)


if __name__ == "__main__":
    unittest.main()
