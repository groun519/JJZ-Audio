from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.command import CommandCancellation, CommandResult
from jang_app.services.rvc_training_filelist import build_rvc_training_filelist
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from jang_app.services.rvc_training_train import (
    RvcTrainingRunError,
    RvcTrainingRunSettings,
    train_rvc_model,
)
from jang_app.services.rvc_training_runtime import RvcTrainingRuntimeInspection
from tests.test_rvc_training_extract import _ready_runtime
from tests.test_rvc_training_filelist import _ready_extraction


class RvcTrainingRunTests(unittest.TestCase):
    def setUp(self) -> None:
        storage = patch(
            "jang_app.services.rvc_training_train.prepare_rvc_training_storage",
            return_value=SimpleNamespace(available_bytes=20 * 1024**3),
        )
        storage.start()
        self.addCleanup(storage.stop)

    def test_runs_managed_v2_training_and_accepts_rvc_completion_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            calls: list[tuple] = []
            progress: list[int] = []

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                calls.append((args, cwd, env))
                _write_training_success(layout, output_callback, target_epoch=20)
                return CommandResult(args, 2333333, "", "Training is done.")

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(),
                progress=progress.append,
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            args, cwd, environment = calls[0]
            self.assertEqual(cwd, layout.root)
            self.assertEqual(Path(args[1]), layout.root / ".jjzero" / "train_rvc.py")
            self.assertIn(
                "train_nsf_sim_cache_sid_load_pretrain.py",
                Path(args[1]).read_text(encoding="utf-8"),
            )
            self.assertIn(
                '"optimizer": None',
                Path(args[1]).read_text(encoding="utf-8"),
            )
            self.assertIn(
                'types.ModuleType("i18n")',
                Path(args[1]).read_text(encoding="utf-8"),
            )
            self.assertEqual(_argument(args, "-e"), layout.rvc_name)
            self.assertEqual(_argument(args, "-sr"), "40k")
            self.assertEqual(_argument(args, "-f0"), "1")
            self.assertEqual(_argument(args, "-l"), "0")
            self.assertEqual(_argument(args, "-sw"), "1")
            self.assertIn(str(runtime.resolve()), environment["PATH"])
            self.assertTrue((layout.root / "configs" / "40k.json").is_file())
            self.assertTrue(result.completed)
            self.assertEqual(result.inference_model, layout.weights_dir / "voice.pth")
            self.assertEqual(result.state.current_epoch, 20)
            self.assertEqual(progress[-1], 100)
            self.assertFalse((runtime / "weights" / "voice.pth").exists())

    def test_cpu_training_disables_half_precision_and_gpu_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            (runtime / "configs" / "40k.json").write_text(
                json.dumps({"train": {"fp16_run": True}}),
                encoding="utf-8",
            )

            def cpu_runtime(root, check_cuda=False):
                return RvcTrainingRuntimeInspection(
                    Path(root).resolve(),
                    (),
                    cuda_available=False,
                    cpu_ready=True,
                )

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                config = json.loads(
                    (layout.root / "configs" / "40k.json").read_text(encoding="utf-8")
                )
                self.assertFalse(config["train"]["fp16_run"])
                self.assertEqual(_argument(args, "-c"), "0")
                _write_training_success(layout, output_callback, target_epoch=20)
                return CommandResult(args, 2333333, "", "Training is done.")

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(cache_in_gpu=True),
                command_runner=runner,
                runtime_inspector=cpu_runtime,
            )

            self.assertTrue(result.completed)

    def test_existing_checkpoint_pair_is_resumed_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            RvcTrainingStateStore(model_id, layout).refresh_checkpoint_pair()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                self.assertTrue((layout.experiment_dir / "G_100.pth").is_file())
                _write_training_success(layout, output_callback, target_epoch=30, step=200)
                return CommandResult(args, 2333333, "", "Training is done.")

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(target_epoch=30),
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertTrue(result.resumed)
            self.assertEqual(result.state.checkpoint_step, 200)
            self.assertFalse((layout.experiment_dir / "G_100.pth").exists())

    def test_incomplete_checkpoint_is_removed_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            _checkpoint_pair(layout, 100)
            incomplete = layout.experiment_dir / "G_200.pth"
            incomplete.write_bytes(b"partial")
            RvcTrainingStateStore(model_id, layout).refresh_checkpoint_pair()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                self.assertFalse(incomplete.exists())
                self.assertTrue((layout.experiment_dir / "G_100.pth").is_file())
                _write_training_success(layout, output_callback, target_epoch=30, step=300)
                return CommandResult(args, 2333333, "", "Training is done.")

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(target_epoch=30),
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertTrue(result.resumed)

    def test_new_training_archives_existing_checkpoints_without_deleting_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(f"old-{name}".encode())
            RvcTrainingStateStore(model_id, layout).refresh_checkpoint_pair()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                self.assertFalse((layout.experiment_dir / "G_100.pth").exists())
                _write_training_success(layout, output_callback, target_epoch=20, step=300)
                return CommandResult(args, 2333333, "", "Training is done.")

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(resume=False),
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            archived = tuple((layout.model_dir / "training" / "history").rglob("[GD]_100.pth"))
            self.assertEqual(len(archived), 2)
            self.assertFalse(result.resumed)
            self.assertEqual(result.state.checkpoint_step, 300)

    def test_cancellation_stops_training_and_restores_previous_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            final_model = layout.weights_dir / "voice.pth"
            final_model.write_bytes(b"previous model")
            cancellation = CommandCancellation()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                final_model.write_bytes(b"partial model")
                _checkpoint_pair(layout, 50)
                if output_callback is not None:
                    output_callback("====> Epoch: 5")
                cancellation.request_cancel()
                return CommandResult(args, 1, "", "stopped", cancelled=True)

            result = train_rvc_model(
                model_id,
                layout,
                runtime,
                RvcTrainingRunSettings(),
                cancellation=cancellation,
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertTrue(result.stopped)
            self.assertEqual(result.state.phase, RvcTrainingPhase.STOPPED)
            self.assertEqual(result.state.current_epoch, 5)
            self.assertEqual(final_model.read_bytes(), b"previous model")
            self.assertEqual(result.state.checkpoint_step, 50)

    def test_failure_restores_previous_model_and_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            final_model = layout.weights_dir / "voice.pth"
            final_model.write_bytes(b"previous model")

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                final_model.write_bytes(b"corrupt")
                return CommandResult(args, 1, "", "CUDA out of memory")

            with self.assertRaises(RvcTrainingRunError):
                train_rvc_model(
                    model_id,
                    layout,
                    runtime,
                    RvcTrainingRunSettings(),
                    command_runner=runner,
                    runtime_inspector=_ready_runtime,
                )

            self.assertEqual(final_model.read_bytes(), b"previous model")
            state = RvcTrainingStateStore(model_id, layout).load()
            self.assertEqual(state.phase, RvcTrainingPhase.FAILED)
            self.assertIn("CUDA out of memory", state.last_error)

    def test_stale_previous_model_is_not_accepted_as_a_new_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            final_model = layout.weights_dir / "voice.pth"
            final_model.write_bytes(b"previous model")

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                _checkpoint_pair(layout, 100)
                return CommandResult(args, 2333333, "", "Training is done.")

            with self.assertRaises(RvcTrainingRunError):
                train_rvc_model(
                    model_id,
                    layout,
                    runtime,
                    RvcTrainingRunSettings(),
                    command_runner=runner,
                    runtime_inspector=_ready_runtime,
                )

            self.assertEqual(final_model.read_bytes(), b"previous model")

    def test_invalid_settings_are_rejected_before_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))

            with self.assertRaises(RvcTrainingRunError):
                train_rvc_model(
                    model_id,
                    layout,
                    runtime,
                    RvcTrainingRunSettings(target_epoch=0),
                    runtime_inspector=_ready_runtime,
                )

            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.FILELIST_READY,
            )


def _training_setup(root: Path):
    model_id, layout, runtime = _ready_extraction(root)
    build_rvc_training_filelist(model_id, layout, runtime)
    return model_id, layout, runtime


def _write_training_success(
    layout,
    output_callback,
    *,
    target_epoch: int,
    step: int = 100,
) -> None:
    _checkpoint_pair(layout, step)
    (layout.weights_dir / f"{layout.rvc_name}.pth").write_bytes(b"inference model")
    with (layout.experiment_dir / "train.log").open("a", encoding="utf-8") as log:
        log.write(f"====> Epoch: {target_epoch}\nTraining is done. The program is closed.\n")
    if output_callback is not None:
        output_callback(
            f"saving ckpt {layout.rvc_name}_e{target_epoch}_s{step}:Success."
        )
        output_callback(f"====> Epoch: {target_epoch}")
        output_callback("Training is done. The program is closed.")


def _checkpoint_pair(layout, step: int) -> None:
    for kind in ("G", "D"):
        (layout.experiment_dir / f"{kind}_{step}.pth").write_bytes(kind.encode())


def _argument(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


if __name__ == "__main__":
    unittest.main()
