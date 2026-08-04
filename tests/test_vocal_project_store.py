from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from jang_app.services.vocal_project import (
    UNASSIGNED_SPEAKER_ID,
    VocalProjectValidationError,
    VocalSegment,
    VocalTake,
)
from jang_app.services.vocal_project_store import VOCAL_PROJECT_MANIFEST, VocalProjectStore


class VocalProjectStoreTests(unittest.TestCase):
    def test_existing_output_becomes_portable_project_with_one_full_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = _job_dir(Path(temporary) / "run")
            converted = _write_wave(job_dir / "vocals_rvc_model.wav")
            store = VocalProjectStore()

            project = store.open_or_create(job_dir, active_converted_path=converted)
            loaded = store.load(job_dir)
            manifest = json.loads((job_dir / VOCAL_PROJECT_MANIFEST).read_text(encoding="utf-8"))

            self.assertEqual(loaded, project)
            self.assertEqual(project.duration_ms, 1000)
            self.assertEqual(len(project.segments), 1)
            self.assertEqual(project.segments[0].speaker_id, UNASSIGNED_SPEAKER_ID)
            self.assertEqual(project.segments[0].end_ms, project.duration_ms)
            self.assertEqual(project.active_take_id, project.takes[0].take_id)
            self.assertEqual(manifest["assets"]["vocals"], "vocals.wav")
            self.assertEqual(manifest["takes"][0]["output"], "vocals_rvc_model.wav")
            self.assertFalse((job_dir / f"{VOCAL_PROJECT_MANIFEST}.tmp").exists())

    def test_new_legacy_take_is_synchronized_without_resetting_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = _job_dir(Path(temporary) / "run")
            store = VocalProjectStore()
            project = store.open_or_create(job_dir)
            edited = replace(
                project,
                segments=(
                    VocalSegment("segment-001", 0, 400, UNASSIGNED_SPEAKER_ID),
                    VocalSegment("segment-002", 400, 1000, UNASSIGNED_SPEAKER_ID, muted=True),
                ),
            )
            edited = store.save(job_dir, edited)
            converted = _write_wave(job_dir / "vocals_rvc_second.wav")

            synchronized = store.open_or_create(job_dir, active_converted_path=converted)

            self.assertEqual(synchronized.project_id, edited.project_id)
            self.assertEqual(synchronized.segments, edited.segments)
            self.assertEqual(len(synchronized.takes), 1)
            self.assertEqual(synchronized.active_take_id, synchronized.takes[0].take_id)

    def test_invalid_project_is_rejected_without_overwriting_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = _job_dir(Path(temporary) / "run")
            store = VocalProjectStore()
            project = store.open_or_create(job_dir)
            original_manifest = (job_dir / VOCAL_PROJECT_MANIFEST).read_bytes()
            invalid = replace(
                project,
                segments=(
                    VocalSegment("segment-001", 0, 700, UNASSIGNED_SPEAKER_ID),
                    VocalSegment("segment-002", 600, 900, UNASSIGNED_SPEAKER_ID),
                ),
            )

            with self.assertRaisesRegex(VocalProjectValidationError, "overlap"):
                store.save(job_dir, invalid)

            self.assertEqual((job_dir / VOCAL_PROJECT_MANIFEST).read_bytes(), original_manifest)

    def test_take_path_cannot_escape_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_dir = _job_dir(root / "run")
            store = VocalProjectStore()
            project = store.open_or_create(job_dir)
            escaped = replace(
                project,
                takes=(
                    VocalTake(
                        "take-outside",
                        "Outside",
                        root / "outside.wav",
                        project.created_at,
                    ),
                ),
            )

            with self.assertRaisesRegex(VocalProjectValidationError, "escapes"):
                store.save(job_dir, escaped)

    def test_corrupt_manifest_is_reported_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = _job_dir(Path(temporary) / "run")
            (job_dir / VOCAL_PROJECT_MANIFEST).write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(VocalProjectValidationError, "Could not read"):
                VocalProjectStore().load(job_dir)

    def test_manifest_path_cannot_escape_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = _job_dir(Path(temporary) / "run")
            store = VocalProjectStore()
            store.open_or_create(job_dir)
            manifest_path = job_dir / VOCAL_PROJECT_MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"]["vocals"] = "../vocals.wav"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(VocalProjectValidationError, "escapes"):
                store.load(job_dir)

    def test_relative_manifest_survives_moving_the_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = _job_dir(root / "original")
            converted = _write_wave(original / "vocals_rvc_move.wav")
            store = VocalProjectStore()
            store.open_or_create(original, active_converted_path=converted)
            moved = root / "moved"
            shutil.copytree(original, moved)

            loaded = store.load(moved)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.vocals_path, moved.resolve() / "vocals.wav")
            self.assertEqual(loaded.takes[0].output_path, moved.resolve() / "vocals_rvc_move.wav")


def _job_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    _write_wave(path / "vocals.wav")
    _write_wave(path / "no_vocals.wav")
    return path


def _write_wave(path: Path, *, sample_rate: int = 8000, duration_seconds: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * sample_rate * duration_seconds)
    return path.resolve()


if __name__ == "__main__":
    unittest.main()
