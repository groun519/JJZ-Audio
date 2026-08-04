from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_dataset import (
    RvcTrainingDatasetError,
    RvcTrainingSnapshotStore,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase


class RvcTrainingSnapshotStoreTests(unittest.TestCase):
    def test_builds_portable_snapshot_from_ready_selected_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id = "created-voice"
            dataset_store = ModelDatasetStore(root / "workspace")
            source = _audio_file(root / "input" / "!!!.wav", b"reviewed voice")
            item = dataset_store.add_sources(model_id, [source]).items[0]
            dataset_store.select_items(model_id, [item.item_id])
            dataset = dataset_store.mark_item_ready(model_id, item.item_id)
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()
            progress: list[int] = []

            snapshot = RvcTrainingSnapshotStore(model_id, layout).build(dataset, progress.append)

            self.assertEqual(len(snapshot.inputs), 1)
            self.assertEqual(snapshot.input_paths[0].name, "0001_audio.wav")
            self.assertEqual(snapshot.input_paths[0].read_bytes(), b"reviewed voice")
            self.assertEqual(progress[-1], 100)
            state = RvcTrainingSnapshotStore(model_id, layout).state_store.load()
            self.assertEqual(state.dataset_fingerprint, snapshot.fingerprint)
            manifest = json.loads((snapshot.root / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["inputs"][0]["path"], "input/0001_audio.wav")

    def test_rejects_selected_material_that_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id = "created-voice"
            dataset_store = ModelDatasetStore(root / "workspace")
            source = _audio_file(root / "voice.wav", b"voice")
            item = dataset_store.add_sources(model_id, [source]).items[0]
            dataset = dataset_store.select_items(model_id, [item.item_id])
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()

            with self.assertRaises(RvcTrainingDatasetError):
                RvcTrainingSnapshotStore(model_id, layout).build(dataset)

            self.assertFalse((layout.model_dir / "training").exists())

    def test_same_content_reuses_snapshot_and_changed_content_resets_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id = "created-voice"
            dataset_store = ModelDatasetStore(root / "workspace")
            source = _audio_file(root / "voice.wav", b"first")
            item = dataset_store.add_sources(model_id, [source]).items[0]
            dataset_store.select_items(model_id, [item.item_id])
            dataset = dataset_store.mark_item_ready(model_id, item.item_id)
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()
            snapshots = RvcTrainingSnapshotStore(model_id, layout)
            first = snapshots.build(dataset)
            state = snapshots.state_store.save(
                replace(snapshots.state_store.load(), phase=RvcTrainingPhase.COMPLETE)
            )

            same = snapshots.build(dataset)
            self.assertEqual(same.root, first.root)
            self.assertEqual(snapshots.state_store.load().phase, state.phase)

            replacement = dataset.items[0].working_path.with_suffix(".new")
            replacement.write_bytes(b"second")
            os.replace(replacement, dataset.items[0].working_path)
            changed = snapshots.build(dataset)

            self.assertNotEqual(changed.fingerprint, first.fingerprint)
            self.assertTrue(first.root.is_dir())
            self.assertEqual(snapshots.state_store.load().phase, RvcTrainingPhase.IDLE)

    def test_copy_fallback_keeps_snapshot_when_hardlink_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id = "created-voice"
            dataset_store = ModelDatasetStore(root / "workspace")
            source = _audio_file(root / "voice.wav", b"voice")
            item = dataset_store.add_sources(model_id, [source]).items[0]
            dataset_store.select_items(model_id, [item.item_id])
            dataset = dataset_store.mark_item_ready(model_id, item.item_id)
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()

            with patch("jang_app.services.managed_files.os.link", side_effect=OSError):
                snapshot = RvcTrainingSnapshotStore(model_id, layout).build(dataset)

            self.assertEqual(snapshot.input_paths[0].read_bytes(), b"voice")

    def test_failed_rebuild_preserves_previous_snapshot_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_id = "created-voice"
            dataset_store = ModelDatasetStore(root / "workspace")
            source = _audio_file(root / "voice.wav", b"first")
            item = dataset_store.add_sources(model_id, [source]).items[0]
            dataset_store.select_items(model_id, [item.item_id])
            dataset = dataset_store.mark_item_ready(model_id, item.item_id)
            layout = RvcModelPackageLayout(root / "model", "voice")
            layout.create()
            snapshots = RvcTrainingSnapshotStore(model_id, layout)
            first = snapshots.build(dataset)
            replacement = dataset.items[0].working_path.with_suffix(".new")
            replacement.write_bytes(b"second")
            os.replace(replacement, dataset.items[0].working_path)

            with patch(
                "jang_app.services.rvc_training_dataset.link_or_copy_file",
                side_effect=RuntimeError("copy failed"),
            ):
                with self.assertRaises(RuntimeError):
                    snapshots.build(dataset)

            current = snapshots.current()
            self.assertIsNotNone(current)
            self.assertEqual(current.fingerprint, first.fingerprint)
            self.assertEqual(current.input_paths[0].read_bytes(), b"first")
            leftovers = [
                path
                for path in snapshots.snapshots_dir.iterdir()
                if path.name.startswith(".building-")
            ]
            self.assertEqual(leftovers, [])


def _audio_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


if __name__ == "__main__":
    unittest.main()
