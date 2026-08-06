from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_state import (
    RvcTrainingPhase,
    RvcTrainingStateError,
    RvcTrainingStateStore,
)


class RvcTrainingStateStoreTests(unittest.TestCase):
    def test_initializes_and_reloads_portable_training_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            store = RvcTrainingStateStore("created-voice", layout)

            initial = store.initialize()
            self.assertEqual(initial, store.load())
            saved = store.save(
                replace(
                    initial,
                    phase=RvcTrainingPhase.PREPROCESS,
                    dataset_fingerprint=f"sha256:{'a' * 64}",
                    target_epoch=30,
                )
            )
            reloaded = RvcTrainingStateStore("created-voice", layout).load()

            self.assertEqual(reloaded, saved)
            self.assertEqual(reloaded.target_epoch, 30)
            raw = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["settings"]["version"], "v2")
            self.assertEqual(raw["settings"]["sample_rate"], 40000)

    def test_dataset_change_resets_phase_without_discarding_training_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            store = RvcTrainingStateStore("created-voice", layout)
            state = store.save(
                replace(
                    store.load(),
                    phase=RvcTrainingPhase.COMPLETE,
                    current_epoch=20,
                    target_epoch=40,
                )
            )

            updated = store.update_dataset_fingerprint(f"sha256:{'b' * 64}")

            self.assertEqual(updated.phase, RvcTrainingPhase.IDLE)
            self.assertEqual(updated.current_epoch, state.current_epoch)
            self.assertEqual(updated.target_epoch, state.target_epoch)

    def test_refresh_uses_latest_complete_checkpoint_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            for name in ("G_100.pth", "D_100.pth", "G_200.pth", "D_150.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            store = RvcTrainingStateStore("created-voice", layout)

            state = store.refresh_checkpoint_pair()

            self.assertEqual(state.checkpoint_step, 100)
            self.assertEqual(state.generator_checkpoint, (layout.experiment_dir / "G_100.pth").resolve())
            self.assertEqual(state.discriminator_checkpoint, (layout.experiment_dir / "D_100.pth").resolve())
            self.assertTrue(state.can_resume)
            raw = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["checkpoint"]["generator"], "rvc/logs/voice/G_100.pth")

    def test_rejects_checkpoint_outside_managed_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()
            store = RvcTrainingStateStore("created-voice", layout)
            initial = store.load()
            external = root / "G_1.pth"
            external.write_bytes(b"checkpoint")

            with self.assertRaises(RvcTrainingStateError):
                store.save(
                    replace(
                        initial,
                        checkpoint_step=1,
                        generator_checkpoint=external,
                        discriminator_checkpoint=external,
                    )
                )

    def test_rejects_checkpoint_pair_with_mismatched_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            generator = layout.experiment_dir / "G_10.pth"
            discriminator = layout.experiment_dir / "D_20.pth"
            generator.write_bytes(b"generator")
            discriminator.write_bytes(b"discriminator")
            store = RvcTrainingStateStore("created-voice", layout)

            with self.assertRaises(RvcTrainingStateError):
                store.save(
                    replace(
                        store.load(),
                        checkpoint_step=20,
                        generator_checkpoint=generator,
                        discriminator_checkpoint=discriminator,
                    )
                )

    def test_rejects_incompatible_or_traversing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            store = RvcTrainingStateStore("created-voice", layout)
            state = store.initialize()
            raw = json.loads(store.path.read_text(encoding="utf-8"))
            raw["checkpoint"] = {
                "step": 1,
                "generator": "../G_1.pth",
                "discriminator": "../D_1.pth",
            }
            store.path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaises(RvcTrainingStateError):
                store.load()

            store.path.write_text(json.dumps({"version": 99, "model_id": state.model_id}), encoding="utf-8")
            with self.assertRaises(RvcTrainingStateError):
                store.load()

    def test_interrupted_training_is_recovered_as_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            store = RvcTrainingStateStore("created-voice", layout)
            store.save(replace(store.load(), phase=RvcTrainingPhase.TRAIN))

            recovered = store.recover_interrupted()

            self.assertEqual(recovered.phase, RvcTrainingPhase.STOPPED)
            self.assertEqual(recovered.checkpoint_step, 100)
            self.assertTrue(recovered.can_resume)

    def test_failure_context_survives_reload_and_clears_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = RvcModelPackageLayout(Path(temporary) / "model", "voice")
            layout.create()
            for name in ("G_100.pth", "D_100.pth"):
                (layout.experiment_dir / name).write_bytes(name.encode())
            store = RvcTrainingStateStore("created-voice", layout)

            failed = store.record_failure_context(
                "CUDA out of memory",
                task_id="task-123",
                diagnostic_code="CUDA_OUT_OF_MEMORY",
            )
            reloaded = RvcTrainingStateStore("created-voice", layout).load()

            self.assertEqual(reloaded, failed)
            self.assertEqual(reloaded.last_task_id, "task-123")
            self.assertEqual(
                reloaded.last_diagnostic_code,
                "CUDA_OUT_OF_MEMORY",
            )
            self.assertTrue(reloaded.can_resume)

            retried = store.begin_training(20)

            self.assertEqual(retried.last_task_id, "")
            self.assertEqual(retried.last_diagnostic_code, "")


if __name__ == "__main__":
    unittest.main()
