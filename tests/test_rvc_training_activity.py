import unittest

from jang_app.services.rvc_training_activity import describe_rvc_training_activity
from jang_app.services.i18n import tr


class RvcTrainingActivityTests(unittest.TestCase):
    def test_describes_pitch_and_feature_progress_without_exposing_paths(self) -> None:
        self.assertEqual(
            describe_rvc_training_activity(
                "f0ing,now-3,all-12,-C:/private/training/clip.wav"
            ),
            tr("Analyzing pitch {current} / {total}", current=4, total=12),
        )
        self.assertEqual(
            describe_rvc_training_activity(
                "now-12,all-3,C:/private/training/clip.wav,(100, 768)"
            ),
            tr("Analyzing voice features {current} / {total}", current=4, total=12),
        )

    def test_describes_checkpoint_and_index_progress(self) -> None:
        self.assertEqual(
            describe_rvc_training_activity("saving ckpt Voice_e20_s400.pth"),
            tr("Saving the epoch {epoch} checkpoint", epoch=20),
        )
        self.assertEqual(
            describe_rvc_training_activity("JJZERO_INDEX_PROGRESS=74"),
            tr("Building the retrieval index {progress}%", progress=74),
        )

    def test_describes_training_start_and_intra_epoch_progress(self) -> None:
        self.assertEqual(
            describe_rvc_training_activity("JJZERO_TRAINING_START current=0 target=20"),
            tr(
                "Preparing epoch {epoch} / {target}; the first epoch can take longer",
                epoch=1,
                target=20,
            ),
        )
        self.assertEqual(
            describe_rvc_training_activity("Train Epoch: 3 [42.4%]"),
            tr("Training epoch {epoch}; current epoch {progress}%", epoch=3, progress=42),
        )

    def test_ignores_unhelpful_runtime_noise(self) -> None:
        self.assertIsNone(describe_rvc_training_activity("FutureWarning: deprecated"))

    def test_describes_single_device_and_first_batch_startup(self) -> None:
        self.assertEqual(
            describe_rvc_training_activity("JJZERO_SINGLE_DEVICE_TRAINING"),
            tr("Initializing single-GPU training"),
        )
        self.assertEqual(
            describe_rvc_training_activity("JJZERO_TRAINING_DATA_LOADER_START"),
            tr("Loading the first training batch"),
        )
        self.assertEqual(
            describe_rvc_training_activity("JJZERO_TRAINING_FIRST_BATCH_READY"),
            tr("First training batch loaded; starting model optimization"),
        )


if __name__ == "__main__":
    unittest.main()
