from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.services.command import CommandCancellation
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.rvc_training_extract import RvcTrainingExtractError
from jang_app.services.rvc_training_filelist import RvcTrainingFilelistError
from jang_app.services.rvc_training_index import RvcTrainingIndexError
from jang_app.services.rvc_training_pipeline import (
    RvcTrainingStage,
    run_rvc_training_pipeline,
)
from jang_app.services.rvc_training_preprocess import RvcTrainingPreprocessError
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from jang_app.services.rvc_training_spectrogram import RvcTrainingSpectrogramError
from jang_app.services.rvc_training_train import RvcTrainingRunResult, RvcTrainingRunSettings
from tests.test_rvc_training_train import _training_setup


class RvcTrainingPipelineTests(unittest.TestCase):
    def test_reuses_every_valid_preparation_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id, layout, runtime = _training_setup(root)
            dataset = ModelDatasetStore(root / "workspace").load(model_id)
            stages: list[RvcTrainingStage] = []
            progress: list[int] = []

            with (
                patch("jang_app.services.rvc_training_pipeline.preprocess_rvc_training_dataset") as preprocess,
                patch("jang_app.services.rvc_training_pipeline.extract_rvc_training_features") as extract,
                patch("jang_app.services.rvc_training_pipeline.build_rvc_training_filelist") as filelist,
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_training_spectrogram_cache",
                    return_value=object(),
                ),
                patch(
                    "jang_app.services.rvc_training_pipeline.prepare_rvc_training_spectrogram_cache"
                ) as spectrogram,
                patch("jang_app.services.rvc_training_pipeline.load_rvc_training_index", return_value=object()),
                patch("jang_app.services.rvc_training_pipeline.build_rvc_training_index") as build_index,
                patch(
                    "jang_app.services.rvc_training_pipeline.train_rvc_model",
                    side_effect=lambda *args, **kwargs: _complete_training(model_id, layout),
                ),
            ):
                result = run_rvc_training_pipeline(
                    model_id,
                    layout,
                    runtime,
                    dataset,
                    RvcTrainingRunSettings(),
                    progress=progress.append,
                    stage_callback=stages.append,
                )

            preprocess.assert_not_called()
            extract.assert_not_called()
            filelist.assert_not_called()
            spectrogram.assert_not_called()
            build_index.assert_not_called()
            self.assertEqual(result.executed_stages, (RvcTrainingStage.TRAIN,))
            self.assertEqual(stages, list(RvcTrainingStage))
            self.assertEqual(progress, sorted(progress))
            self.assertTrue(
                all(boundary in progress for boundary in (10, 30, 55, 60, 70, 92, 100))
            )
            self.assertTrue(result.completed)

    def test_changed_dataset_rebuilds_each_dependent_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id, layout, runtime = _training_setup(root)
            store = ModelDatasetStore(root / "workspace")
            dataset = store.load(model_id)
            dataset.training_items[0].working_path.write_bytes(b"changed material")

            with (
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_preprocess_result",
                    side_effect=RvcTrainingPreprocessError("stale"),
                ),
                patch("jang_app.services.rvc_training_pipeline.preprocess_rvc_training_dataset", return_value=object()) as preprocess,
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_extract_result",
                    side_effect=RvcTrainingExtractError("stale"),
                ),
                patch("jang_app.services.rvc_training_pipeline.extract_rvc_training_features", return_value=object()) as extract,
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_training_filelist",
                    side_effect=RvcTrainingFilelistError("stale"),
                ),
                patch("jang_app.services.rvc_training_pipeline.build_rvc_training_filelist", return_value=object()) as filelist,
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_training_spectrogram_cache",
                    side_effect=RvcTrainingSpectrogramError("stale"),
                ),
                patch(
                    "jang_app.services.rvc_training_pipeline.prepare_rvc_training_spectrogram_cache",
                    return_value=object(),
                ) as spectrogram,
                patch(
                    "jang_app.services.rvc_training_pipeline.load_rvc_training_index",
                    side_effect=RvcTrainingIndexError("stale"),
                ),
                patch("jang_app.services.rvc_training_pipeline.build_rvc_training_index", return_value=object()) as index,
                patch(
                    "jang_app.services.rvc_training_pipeline.train_rvc_model",
                    side_effect=lambda *args, **kwargs: _complete_training(model_id, layout),
                ),
            ):
                result = run_rvc_training_pipeline(
                    model_id,
                    layout,
                    runtime,
                    dataset,
                    RvcTrainingRunSettings(),
                )

            preprocess.assert_called_once()
            extract.assert_called_once()
            filelist.assert_called_once()
            spectrogram.assert_called_once()
            index.assert_called_once()
            self.assertEqual(result.executed_stages, tuple(RvcTrainingStage))

    def test_cancellation_between_stages_returns_stopped_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id, layout, runtime = _training_setup(root)
            dataset = ModelDatasetStore(root / "workspace").load(model_id)
            cancellation = CommandCancellation()

            def stage_changed(stage: RvcTrainingStage) -> None:
                if stage == RvcTrainingStage.PREPROCESS:
                    cancellation.request_cancel()

            with patch("jang_app.services.rvc_training_pipeline.train_rvc_model") as train:
                result = run_rvc_training_pipeline(
                    model_id,
                    layout,
                    runtime,
                    dataset,
                    RvcTrainingRunSettings(),
                    cancellation=cancellation,
                    stage_callback=stage_changed,
                )

            train.assert_not_called()
            self.assertTrue(result.stopped)
            self.assertEqual(result.executed_stages, ())


def _complete_training(model_id, layout) -> RvcTrainingRunResult:
    store = RvcTrainingStateStore(model_id, layout)
    state = store.save(
        replace(
            store.load(),
            phase=RvcTrainingPhase.COMPLETE,
            current_epoch=20,
            target_epoch=20,
        )
    )
    return RvcTrainingRunResult(
        state=state,
        inference_model=layout.weights_dir / f"{layout.rvc_name}.pth",
        log_path=layout.experiment_dir / "train.log",
        resumed=False,
        stopped=False,
    )


if __name__ == "__main__":
    unittest.main()
