from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.command import CommandCancellation, CommandResult
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_dataset import RvcTrainingSnapshotStore
from jang_app.services.rvc_training_control import RvcTrainingCancelled
from jang_app.services.rvc_training_preprocess import (
    RvcTrainingPreprocessError,
    preprocess_rvc_training_dataset,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


class RvcTrainingPreprocessTests(unittest.TestCase):
    def test_cancellation_is_recorded_as_stopped_instead_of_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _root, model_id, layout, runtime = _training_setup(Path(temporary))
            cancellation = CommandCancellation()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                cancellation.request_cancel()
                return CommandResult(args, 1, "", "stopped", cancelled=True)

            with self.assertRaises(RvcTrainingCancelled):
                preprocess_rvc_training_dataset(
                    model_id,
                    layout,
                    runtime,
                    cancellation=cancellation,
                    cancellable_runner=runner,
                )

            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.STOPPED,
            )

    def test_runs_preprocess_and_publishes_only_validated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, model_id, layout, runtime = _training_setup(Path(temporary))
            experiment = layout.experiment_dir
            (experiment / "2a_f0").mkdir()
            (experiment / "2a_f0" / "old.npy").write_bytes(b"old feature")
            (experiment / "G_100.pth").write_bytes(b"checkpoint")
            (experiment / "added_voice.index").write_bytes(b"index")
            calls: list[tuple] = []
            progress: list[int] = []

            def runner(args, cwd=None, env=None, output_callback=None):
                calls.append((args, cwd, env))
                _write_success_outputs(Path(args[5]), Path(args[2]), output_callback)
                return CommandResult(args, 0, "", "")

            result = preprocess_rvc_training_dataset(
                model_id,
                layout,
                runtime,
                worker_count=99,
                progress=progress.append,
                command_runner=runner,
            )

            self.assertEqual(len(result.gt_wavs), 1)
            self.assertEqual(len(result.wavs_16k), 1)
            self.assertEqual(calls[0][1], runtime.resolve())
            self.assertLessEqual(int(calls[0][0][4]), 8)
            self.assertTrue((experiment / "G_100.pth").is_file())
            self.assertTrue((experiment / "added_voice.index").is_file())
            self.assertFalse((experiment / "2a_f0").exists())
            self.assertEqual(progress[-1], 100)
            state = RvcTrainingStateStore(model_id, layout).load()
            self.assertEqual(state.phase, RvcTrainingPhase.PREPROCESSED)
            self.assertEqual(state.last_error, "")

    def test_command_failure_preserves_previous_outputs_and_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _root, model_id, layout, runtime = _training_setup(Path(temporary))
            old_output = layout.experiment_dir / "0_gt_wavs" / "old.wav"
            old_output.parent.mkdir()
            old_output.write_bytes(b"old")

            def runner(args, cwd=None, env=None, output_callback=None):
                return CommandResult(args, 1, "", "decode failed")

            with self.assertRaises(RvcTrainingPreprocessError):
                preprocess_rvc_training_dataset(
                    model_id,
                    layout,
                    runtime,
                    command_runner=runner,
                )

            self.assertEqual(old_output.read_bytes(), b"old")
            state = RvcTrainingStateStore(model_id, layout).load()
            self.assertEqual(state.phase, RvcTrainingPhase.FAILED)
            self.assertIn("decode failed", state.last_error)

    def test_partial_success_is_rejected_without_replacing_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, model_id, layout, runtime = _training_setup(Path(temporary), input_count=2)
            old_output = layout.experiment_dir / "1_16k_wavs" / "old.wav"
            old_output.parent.mkdir()
            old_output.write_bytes(b"old")

            def runner(args, cwd=None, env=None, output_callback=None):
                staging = Path(args[5])
                _write_output_pair(staging, "0_0")
                (staging / "preprocess.log").write_text("first->Suc.\nsecond->Traceback\n", encoding="utf-8")
                return CommandResult(args, 0, "", "")

            with self.assertRaises(RvcTrainingPreprocessError):
                preprocess_rvc_training_dataset(
                    model_id,
                    layout,
                    runtime,
                    command_runner=runner,
                )

            self.assertEqual(old_output.read_bytes(), b"old")
            leftovers = tuple((root / "model" / "training" / "preprocess").glob(".building-*"))
            self.assertEqual(leftovers, ())

    def test_publish_failure_rolls_back_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _root, model_id, layout, runtime = _training_setup(Path(temporary))
            old_gt = layout.experiment_dir / "0_gt_wavs" / "old.wav"
            old_16k = layout.experiment_dir / "1_16k_wavs" / "old.wav"
            for path in (old_gt, old_16k):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"old")

            def runner(args, cwd=None, env=None, output_callback=None):
                _write_success_outputs(Path(args[5]), Path(args[2]), output_callback)
                return CommandResult(args, 0, "", "")

            real_move = shutil.move
            did_fail = False

            def fail_new_16k_once(source, target):
                nonlocal did_fail
                if not did_fail and Path(source).name == "1_16k_wavs" and ".building-" in str(source):
                    did_fail = True
                    raise OSError("publish failed")
                return real_move(source, target)

            with patch(
                "jang_app.services.rvc_training_artifacts.shutil.move",
                side_effect=fail_new_16k_once,
            ):
                with self.assertRaises(RvcTrainingPreprocessError):
                    preprocess_rvc_training_dataset(
                        model_id,
                        layout,
                        runtime,
                        command_runner=runner,
                    )

            self.assertEqual(old_gt.read_bytes(), b"old")
            self.assertEqual(old_16k.read_bytes(), b"old")
            backups = tuple(layout.experiment_dir.glob(".jjzero-preprocess-backup-*"))
            self.assertEqual(backups, ())


def _training_setup(
    root: Path,
    *,
    input_count: int = 1,
) -> tuple[Path, str, RvcModelPackageLayout, Path]:
    model_id = "created-voice"
    dataset_store = ModelDatasetStore(root / "workspace")
    sources = [
        _audio_file(root / "inputs" / f"voice-{index}.wav", f"voice-{index}".encode())
        for index in range(input_count)
    ]
    dataset = dataset_store.add_sources(model_id, sources)
    dataset_store.select_items(model_id, [item.item_id for item in dataset.items])
    for item in dataset.items:
        dataset_store.mark_item_ready(model_id, item.item_id)
    layout = RvcModelPackageLayout(root / "model", "voice")
    layout.create()
    RvcTrainingSnapshotStore(model_id, layout).build(dataset_store.load(model_id))
    runtime = root / "runtime"
    for relative_path in required_rvc_training_paths():
        path = runtime / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    return root, model_id, layout, runtime


def _write_success_outputs(
    staging: Path,
    input_dir: Path,
    output_callback,
) -> None:
    log_lines: list[str] = []
    for index, source in enumerate(sorted(input_dir.iterdir())):
        _write_output_pair(staging, f"{index}_0")
        line = f"{source}->Suc."
        log_lines.append(line)
        if output_callback is not None:
            output_callback(line)
    (staging / "preprocess.log").write_text("\n".join(log_lines), encoding="utf-8")


def _write_output_pair(staging: Path, stem: str) -> None:
    for directory in ("0_gt_wavs", "1_16k_wavs"):
        target = staging / directory / f"{stem}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"wave")


def _audio_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


if __name__ == "__main__":
    unittest.main()
