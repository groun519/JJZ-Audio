from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from jang_app.services.command import CommandCancellation, CommandResult
from jang_app.services.rvc_training_control import RvcTrainingCancelled
from jang_app.services.rvc_training_index import (
    RvcTrainingIndexError,
    build_rvc_training_index,
    load_rvc_training_index,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from tests.test_rvc_training_filelist import _ready_extraction


class RvcTrainingIndexTests(unittest.TestCase):
    def test_builds_and_publishes_validated_index_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary), input_count=2)
            progress: list[int] = []

            result = build_rvc_training_index(
                model_id,
                layout,
                runtime,
                progress=progress.append,
                command_runner=_index_runner,
            )

            self.assertEqual(result.feature_count, 2)
            self.assertEqual(result.source_vector_count, 4)
            self.assertEqual(result.indexed_vector_count, 4)
            self.assertTrue(result.added_index.name.startswith("added_IVF1_"))
            self.assertEqual(progress, [0, 20, 60, 100, 100])
            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.INDEX_READY,
            )

    def test_modified_index_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            result = build_rvc_training_index(
                model_id,
                layout,
                runtime,
                command_runner=_index_runner,
            )
            result.added_index.write_bytes(b"modified")

            with self.assertRaises(RvcTrainingIndexError):
                load_rvc_training_index(model_id, layout)

    def test_invalid_rebuild_preserves_previous_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            first = build_rvc_training_index(
                model_id,
                layout,
                runtime,
                command_runner=_index_runner,
            )
            original = first.added_index.read_bytes()

            def invalid_runner(args, **kwargs):
                return _index_runner(args, invalid_total=True, **kwargs)

            with self.assertRaises(RvcTrainingIndexError):
                build_rvc_training_index(
                    model_id,
                    layout,
                    runtime,
                    command_runner=invalid_runner,
                )

            self.assertEqual(first.added_index.read_bytes(), original)

    def test_cancellation_is_recorded_as_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            cancellation = CommandCancellation()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                cancellation.request_cancel()
                return CommandResult(args, 1, "", "stopped", cancelled=True)

            with self.assertRaises(RvcTrainingCancelled):
                build_rvc_training_index(
                    model_id,
                    layout,
                    runtime,
                    cancellation=cancellation,
                    command_runner=runner,
                )

            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.STOPPED,
            )


def _index_runner(
    args,
    cwd=None,
    env=None,
    output_callback=None,
    cancellation=None,
    *,
    invalid_total: bool = False,
):
    feature_dir = Path(args[3])
    output_dir = Path(args[4])
    output_dir.mkdir(parents=True)
    arrays = [np.load(path, allow_pickle=False) for path in sorted(feature_dir.glob("*.npy"))]
    features = np.concatenate(arrays, axis=0)
    if invalid_total:
        features[0, 0] = np.nan
    np.save(output_dir / "total_fea.npy", features, allow_pickle=False)
    trained_name = "trained_IVF1_Flat_nprobe_1_voice_v2.index"
    added_name = "added_IVF1_Flat_nprobe_1_voice_v2.index"
    (output_dir / trained_name).write_bytes(b"trained index")
    (output_dir / added_name).write_bytes(b"added index")
    report = {
        "version": 1,
        "feature_count": len(arrays),
        "source_vector_count": int(features.shape[0]),
        "vector_count": int(features.shape[0]),
        "dimension": 768,
        "trained_index": trained_name,
        "added_index": added_name,
        "total_features": "total_fea.npy",
    }
    for value in (20, 60, 100):
        if output_callback is not None:
            output_callback(f"JJZERO_INDEX_PROGRESS={value}")
    return CommandResult(args, 0, json.dumps(report), "")


if __name__ == "__main__":
    unittest.main()
