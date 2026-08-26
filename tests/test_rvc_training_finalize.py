from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.command import CommandResult
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.rvc_training_finalize import (
    RvcTrainingFinalizeError,
    finalize_rvc_training_artifacts,
    inspect_rvc_inference_model,
    recover_existing_rvc_training_artifacts,
)
from jang_app.services.rvc_training_index import (
    RvcTrainingIndexError,
    RvcTrainingIndexResult,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


class RvcTrainingFinalizeTests(unittest.TestCase):
    def test_validated_artifacts_are_registered_in_the_model_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice", runtime)
            layout = RvcModelPackageLayout(workspace.library_dir / record.model_id, record.name)
            model = layout.weights_dir / "Voice.pth"
            model.write_bytes(b"model")
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            added = layout.experiment_dir / "added_voice.index"
            trained = layout.experiment_dir / "trained_voice.index"
            total = layout.experiment_dir / "total_fea.npy"
            for path in (added, trained, total):
                path.write_bytes(b"artifact")
            index = RvcTrainingIndexResult(
                layout.experiment_dir,
                trained,
                added,
                total,
                "",
                1,
                2,
                2,
            )

            with patch(
                "jang_app.services.rvc_training_finalize.load_rvc_training_index",
                return_value=index,
            ):
                result = finalize_rvc_training_artifacts(
                    workspace,
                    record.model_id,
                    layout,
                    runtime,
                    command_runner=_valid_model_runner,
                )

            reloaded = workspace.records()[0]
            self.assertEqual(result.record, reloaded)
            self.assertEqual(reloaded.inference_model, model)
            self.assertEqual(reloaded.index_file, added)
            self.assertEqual(reloaded.generator_checkpoint.name, "G_100.pth")
            self.assertEqual(
                RvcTrainingStateStore(record.model_id, layout).load().phase,
                RvcTrainingPhase.COMPLETE,
            )

    def test_wrong_profile_model_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            model = root / "model.pth"
            model.write_bytes(b"model")

            def runner(args, **kwargs):
                report = {"version": "v1", "sample_rate": 40000, "f0": True, "weight_count": 1}
                return CommandResult(args, 0, json.dumps(report), "")

            with self.assertRaises(RvcTrainingFinalizeError):
                inspect_rvc_inference_model(model, runtime, command_runner=runner)

    def test_model_report_is_read_when_stderr_contains_a_torch_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            model = root / "model.pth"
            model.write_bytes(b"model")

            def runner(args, **kwargs):
                report = {
                    "version": "v2",
                    "sample_rate": 40000,
                    "f0": True,
                    "epoch_info": "900epoch",
                    "weight_count": 457,
                }
                warning = "UserWarning: TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD detected"
                return CommandResult(args, 0, json.dumps(report), warning)

            inspection = inspect_rvc_inference_model(
                model,
                runtime,
                command_runner=runner,
            )

            self.assertEqual(inspection.epoch_info, "900epoch")
            self.assertEqual(inspection.weight_count, 457)

    def test_failed_registration_recovers_preserved_training_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice", runtime)
            layout = RvcModelPackageLayout(
                workspace.library_dir / record.model_id,
                record.name,
            )
            model = layout.weights_dir / "Voice.pth"
            model.write_bytes(b"model")
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            added = layout.experiment_dir / "added_voice.index"
            trained = layout.experiment_dir / "trained_voice.index"
            total = layout.experiment_dir / "total_fea.npy"
            for path in (added, trained, total):
                path.write_bytes(b"artifact")
            index = RvcTrainingIndexResult(
                layout.experiment_dir,
                trained,
                added,
                total,
                "",
                1,
                2,
                2,
            )
            RvcTrainingStateStore(record.model_id, layout).update_phase(
                RvcTrainingPhase.FAILED,
                last_error="Registration failed.",
            )

            with patch(
                "jang_app.services.rvc_training_finalize.load_rvc_training_index",
                return_value=index,
            ):
                result = recover_existing_rvc_training_artifacts(
                    workspace,
                    record.model_id,
                    layout,
                    runtime,
                    command_runner=_valid_model_runner,
                )

            self.assertIsNotNone(result)
            self.assertEqual(result.record.inference_model, model)
            self.assertEqual(
                RvcTrainingStateStore(record.model_id, layout).load().phase,
                RvcTrainingPhase.COMPLETE,
            )

    def test_recovery_does_not_claim_an_incomplete_training_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice", runtime)
            layout = RvcModelPackageLayout(
                workspace.library_dir / record.model_id,
                record.name,
            )
            RvcTrainingStateStore(record.model_id, layout).update_phase(
                RvcTrainingPhase.FAILED,
                last_error="Training failed.",
            )

            result = recover_existing_rvc_training_artifacts(
                workspace,
                record.model_id,
                layout,
                runtime,
                command_runner=_valid_model_runner,
            )

            self.assertIsNone(result)

    def test_complete_phase_without_index_rebuilds_and_registers_without_retraining(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = _runtime(root / "runtime")
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice", runtime)
            layout = RvcModelPackageLayout(
                workspace.library_dir / record.model_id,
                record.name,
            )
            model = layout.weights_dir / "Voice.pth"
            model.write_bytes(b"model")
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            state_store = RvcTrainingStateStore(record.model_id, layout)
            state_store.refresh_checkpoint_pair()
            state_store.update_phase(RvcTrainingPhase.COMPLETE)
            index = RvcTrainingIndexResult(
                layout.experiment_dir,
                layout.experiment_dir / "trained_voice.index",
                layout.experiment_dir / "added_voice.index",
                layout.experiment_dir / "total_fea.npy",
                "",
                1,
                2,
                2,
            )
            for path in (index.trained_index, index.added_index, index.total_features):
                path.write_bytes(b"artifact")

            with (
                patch(
                    "jang_app.services.rvc_training_finalize.load_rvc_training_index",
                    side_effect=[RvcTrainingIndexError("missing"), index],
                ),
                patch(
                    "jang_app.services.rvc_training_finalize.build_rvc_training_index",
                    return_value=index,
                ) as build_index,
            ):
                result = recover_existing_rvc_training_artifacts(
                    workspace,
                    record.model_id,
                    layout,
                    runtime,
                    command_runner=_valid_model_runner,
                )

            self.assertIsNotNone(result)
            build_index.assert_called_once()
            self.assertEqual(state_store.load().phase, RvcTrainingPhase.COMPLETE)


def _valid_model_runner(args, **kwargs):
    report = {
        "version": "v2",
        "sample_rate": 40000,
        "f0": True,
        "epoch_info": "20epoch",
        "weight_count": 10,
    }
    return CommandResult(args, 0, json.dumps(report), "")


def _runtime(root: Path) -> Path:
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "python.exe").write_bytes(b"runtime")
    (root / "infer_cli.py").write_bytes(b"script")
    return root


if __name__ == "__main__":
    unittest.main()
