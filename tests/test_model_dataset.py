from __future__ import annotations

import tempfile
import unittest
import wave
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.clip_edit_history import (
    REVIEW_EDITING,
    REVIEW_READY,
    TRAINING_MODE_CLIPS,
)
from jang_app.services.model_dataset import ModelDatasetError, ModelDatasetStore
from jang_app.services.segment_review import SEGMENT_HELD, SEGMENT_REJECTED


class ModelDatasetStoreTests(unittest.TestCase):
    def test_add_sources_creates_original_and_independent_working_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _audio_file(root / "inputs" / "voice.wav", b"original audio")
            progress: list[int] = []
            store = ModelDatasetStore(root / "workspace")

            dataset = store.add_sources("managed-model", [source], progress.append)
            item = dataset.items[0]

            self.assertEqual(source.read_bytes(), b"original audio")
            self.assertEqual(item.original_path.read_bytes(), b"original audio")
            self.assertEqual(item.working_path.read_bytes(), b"original audio")
            item.working_path.write_bytes(b"edited audio")
            self.assertEqual(item.original_path.read_bytes(), b"original audio")
            self.assertEqual(source.read_bytes(), b"original audio")
            self.assertEqual(progress[-1], 100)

    def test_selection_order_and_deselection_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = [_audio_file(root / f"voice-{index}.wav", bytes([index])) for index in range(3)]
            store = ModelDatasetStore(root / "workspace")
            dataset = store.add_sources("linked-model", sources)
            first, second, _third = dataset.items

            store.select_items("linked-model", [second.item_id, first.item_id])
            reordered = store.move_selected_item("linked-model", first.item_id, -1)
            self.assertEqual([item.item_id for item in reordered.training_items], [first.item_id, second.item_id])

            reloaded = ModelDatasetStore(root / "workspace").load("linked-model")
            self.assertEqual([item.item_id for item in reloaded.training_items], [first.item_id, second.item_id])
            deselected = store.deselect_items("linked-model", [first.item_id])
            self.assertEqual([item.item_id for item in deselected.training_items], [second.item_id])
            self.assertIn(first.item_id, [item.item_id for item in deselected.source_items])

    def test_remove_deletes_workspace_copies_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _audio_file(root / "voice.flac", b"keep source")
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("model", [source]).items[0]

            dataset = store.remove_items("model", [item.item_id])

            self.assertEqual(dataset.items, ())
            self.assertFalse(item.original_path.exists())
            self.assertFalse(item.working_path.exists())
            self.assertEqual(source.read_bytes(), b"keep source")

    def test_duplicate_sources_are_ignored_and_invalid_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _audio_file(root / "voice.wav", b"audio")
            store = ModelDatasetStore(root / "workspace")

            first = store.add_sources("model", [source, source])
            second = store.add_sources("model", [source])

            self.assertEqual(len(first.items), 1)
            self.assertEqual(len(second.items), 1)
            invalid = _audio_file(root / "notes.txt", b"not audio")
            with self.assertRaises(ModelDatasetError):
                store.add_sources("model", [invalid])

    def test_clips_persist_and_reset_restores_working_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _wave_file(root / "voice.wav", duration_ms=1200)
            original_bytes = source.read_bytes()
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("model", [source]).items[0]

            store.add_clip("model", item.item_id, 100, 600)
            second = store.add_clip("model", item.item_id, 650, 1100)
            clips = second.items[0].clips

            self.assertEqual(len(clips), 2)
            self.assertTrue(all(clip.path.is_file() for clip in clips))
            self.assertTrue(490 <= read_audio_metadata(clips[0].path).duration_ms <= 510)
            self.assertEqual(second.items[0].training_duration_ms, 950)
            reloaded = ModelDatasetStore(root / "workspace").load("model")
            self.assertEqual([clip.clip_id for clip in reloaded.items[0].clips], [clip.clip_id for clip in clips])

            store.remove_clip("model", item.item_id, clips[0].clip_id)
            self.assertEqual(len(store.load("model").items[0].clips), 1)
            store.undo_last_clip("model", item.item_id)
            self.assertEqual(len(store.load("model").items[0].clips), 2)
            store.redo_edit("model", item.item_id)
            self.assertEqual(len(store.load("model").items[0].clips), 1)

            with_clip = store.add_clip("model", item.item_id, 0, 500)
            with_clip.items[0].working_path.write_bytes(b"edited")
            reset = store.reset_item("model", item.item_id)
            self.assertEqual(reset.items[0].clips, ())
            self.assertEqual(reset.items[0].working_path.read_bytes(), original_bytes)
            self.assertFalse(with_clip.items[0].clips[0].path.exists())

    def test_add_clips_preserves_manual_clips_and_skips_duplicate_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _wave_file(root / "voice.wav", duration_ms=1200)
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("model", [source]).items[0]
            manual = store.add_clip("model", item.item_id, 100, 300).items[0].clips[0]
            progress: list[int] = []

            dataset = store.add_clips(
                "model",
                item.item_id,
                ((100, 300), (350, 550), (600, 900)),
                progress.append,
            )

            clips = dataset.items[0].clips
            self.assertEqual(clips[0].clip_id, manual.clip_id)
            self.assertEqual([(clip.start_ms, clip.end_ms) for clip in clips], [(100, 300), (350, 550), (600, 900)])
            self.assertTrue(all(clip.path.is_file() for clip in clips))
            self.assertEqual(progress[-1], 100)

    def test_last_clip_removal_does_not_fall_back_to_full_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            source = _wave_file(root / "voice.wav", duration_ms=1200)
            item = store.add_sources("model", [source]).items[0]
            edited = store.add_clip("model", item.item_id, 100, 600).items[0]

            empty = store.remove_clip("model", item.item_id, edited.clips[0].clip_id).items[0]

            self.assertEqual(empty.training_mode, TRAINING_MODE_CLIPS)
            self.assertEqual(empty.training_paths, ())
            self.assertEqual(empty.training_duration_ms, 0)
            with self.assertRaises(ModelDatasetError):
                store.mark_item_ready("model", item.item_id)
            restored = store.undo_edit("model", item.item_id).items[0]
            self.assertEqual([(clip.start_ms, clip.end_ms) for clip in restored.clips], [(100, 600)])
            self.assertTrue(restored.clips[0].path.is_file())
            self.assertEqual(store.redo_edit("model", item.item_id).items[0].training_paths, ())

    def test_update_split_and_undo_preserve_original_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _wave_file(root / "voice.wav", duration_ms=1600)
            original_bytes = source.read_bytes()
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("model", [source]).items[0]
            clip = store.add_clip("model", item.item_id, 100, 1100).items[0].clips[0]
            ready = store.mark_item_ready("model", item.item_id).items[0]
            self.assertEqual(ready.review_state, REVIEW_READY)

            updated = store.update_clip("model", item.item_id, clip.clip_id, 200, 1000).items[0]
            self.assertEqual(updated.review_state, REVIEW_EDITING)
            self.assertEqual([(value.start_ms, value.end_ms) for value in updated.clips], [(200, 1000)])
            self.assertTrue(790 <= read_audio_metadata(updated.clips[0].path).duration_ms <= 810)

            restored = store.undo_edit("model", item.item_id).items[0]
            self.assertEqual(restored.review_state, REVIEW_READY)
            self.assertEqual([(value.start_ms, value.end_ms) for value in restored.clips], [(100, 1100)])
            redone = store.redo_edit("model", item.item_id).items[0]
            split = store.split_clip("model", item.item_id, redone.clips[0].clip_id, 600).items[0]
            self.assertEqual([(value.start_ms, value.end_ms) for value in split.clips], [(200, 600), (600, 1000)])
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(split.original_path.read_bytes(), original_bytes)

    def test_version_two_manifest_migrates_edit_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            source = _wave_file(root / "voice.wav", duration_ms=800)
            item = store.add_sources("model", [source]).items[0]
            store.add_clip("model", item.item_id, 100, 500)
            manifest = store.root / "model" / "dataset.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["version"] = 2
            for raw_item in data["items"]:
                raw_item.pop("training_mode", None)
                raw_item.pop("review_state", None)
                raw_item.pop("edit_history", None)
            manifest.write_text(json.dumps(data), encoding="utf-8")

            migrated = store.load("model").items[0]

            self.assertEqual(migrated.training_mode, TRAINING_MODE_CLIPS)
            self.assertEqual(migrated.review_state, REVIEW_EDITING)

    def test_segment_review_queue_persists_and_accepts_refined_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            source = _wave_file(root / "voice.wav", duration_ms=4000)
            item = store.add_sources("model", [source]).items[0]

            queued = store.replace_segment_candidates(
                "model",
                item.item_id,
                ((100, 1000), (1400, 2600), (3000, 3800)),
            ).items[0]
            held_id = queued.segment_candidates[1].candidate_id
            rejected_id = queued.segment_candidates[2].candidate_id
            store.set_segment_candidate_status("model", item.item_id, held_id, SEGMENT_HELD)
            reviewed = store.set_segment_candidate_status("model", item.item_id, rejected_id, SEGMENT_REJECTED)

            reloaded = ModelDatasetStore(root / "workspace").load("model").items[0]
            self.assertEqual(
                [candidate.status for candidate in reloaded.segment_candidates],
                ["pending", "held", "rejected"],
            )
            with self.assertRaises(ModelDatasetError):
                store.mark_item_ready("model", item.item_id)

            pending_id = reviewed.items[0].segment_candidates[0].candidate_id
            accepted = store.accept_segment_candidate(
                "model",
                item.item_id,
                pending_id,
                150,
                950,
            ).items[0]

            self.assertEqual([(clip.start_ms, clip.end_ms) for clip in accepted.clips], [(150, 950)])
            self.assertNotIn(pending_id, [candidate.candidate_id for candidate in accepted.segment_candidates])
            self.assertTrue(accepted.clips[0].path.is_file())

    def test_denoise_rerenders_same_clip_ranges_and_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _wave_file(root / "voice.wav", duration_ms=1600)
            original_bytes = source.read_bytes()
            store = ModelDatasetStore(root / "workspace")
            item = store.add_sources("model", [source]).items[0]
            clipped = store.add_clip("model", item.item_id, 200, 1200).items[0]
            old_clip = clipped.clips[0]

            def fake_denoise(input_path, output_path, _strength, _sample_start, _sample_end, progress):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(input_path, output_path)
                if progress is not None:
                    progress(100)
                return output_path

            with patch("jang_app.services.model_dataset.render_denoised_audio", side_effect=fake_denoise):
                denoised = store.apply_denoise("model", item.item_id, 65, 0, 500).items[0]

            denoised_path = denoised.denoised_path
            self.assertIsNotNone(denoised_path)
            self.assertTrue(denoised.has_denoised_audio)
            self.assertEqual(denoised.denoise_strength, 65)
            self.assertEqual((denoised.denoise_sample_start_ms, denoised.denoise_sample_end_ms), (0, 500))
            self.assertEqual([(clip.start_ms, clip.end_ms) for clip in denoised.clips], [(200, 1200)])
            self.assertNotEqual(denoised.clips[0].clip_id, old_clip.clip_id)
            self.assertFalse(old_clip.path.exists())
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(denoised.working_path.read_bytes(), original_bytes)

            restored = store.remove_denoise("model", item.item_id).items[0]

            self.assertFalse(restored.has_denoised_audio)
            self.assertEqual(restored.active_audio_path, restored.working_path)
            self.assertEqual([(clip.start_ms, clip.end_ms) for clip in restored.clips], [(200, 1200)])
            self.assertFalse(denoised_path.exists())


def _audio_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _wave_file(path: Path, duration_ms: int) -> Path:
    sample_rate = 8000
    frame_count = round(sample_rate * duration_ms / 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frame_count)
    return path


if __name__ == "__main__":
    unittest.main()
