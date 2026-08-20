from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.pipeline.vocal_cleanup import render_vocal_cleanup
from jang_app.services.vocal_cleanup import VocalCleanupProject
from jang_app.services.vocal_cleanup_store import VocalCleanupStore, VocalCleanupStoreError


class VocalCleanupStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.job_dir = self.root / "result"
        self.job_dir.mkdir()
        self.source = self.job_dir / "vocals.wav"
        samples = np.zeros((44_100, 2), dtype=np.float32)
        samples[:, 0] = np.linspace(-0.5, 0.5, len(samples), dtype=np.float32)
        samples[:, 1] = samples[:, 0]
        sf.write(self.source, samples, 44_100, subtype="FLOAT")
        self.store = VocalCleanupStore()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_project_round_trip_preserves_region_and_result(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed, removed = self._preview_segments("first", 13_230)
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=100,
            end_ms=400,
            effect="dereverb",
            strength="standard",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        result_path = self.store.create_result_path(self.job_dir)
        sf.write(result_path, np.zeros((44_100, 2), dtype=np.float32), 44_100)
        project = self.store.register_result(self.job_dir, project, result_path)

        restored = self.store.load(self.job_dir, self.source)

        self.assertEqual(len(restored.regions), 1)
        self.assertEqual(restored.regions[0].strength, "standard")
        self.assertTrue(restored.regions[0].processed_segment_path.is_file())
        self.assertEqual(len(restored.results), 1)
        self.assertTrue(restored.results[0].path.is_file())

    def test_overlapping_regions_are_rejected(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed, removed = self._preview_segments("first", 13_230)
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=100,
            end_ms=400,
            effect="dereverb",
            strength="standard",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        processed, removed = self._preview_segments("second", 8_820)

        with self.assertRaises(VocalCleanupStoreError):
            self.store.import_preview(
                self.job_dir,
                project,
                start_ms=300,
                end_ms=500,
                effect="dereverb",
                strength="standard",
                processed_segment_path=processed,
                removed_segment_path=removed,
            )
        self.assertTrue(processed.is_file())
        self.assertTrue(removed.is_file())

    def test_render_keeps_length_channels_and_unselected_audio(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed = self.root / "processed.wav"
        removed = self.root / "removed.wav"
        replacement = np.full((13_230, 2), 0.25, dtype=np.float32)
        sf.write(processed, replacement, 44_100, subtype="FLOAT")
        sf.write(removed, replacement, 44_100, subtype="FLOAT")
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=400,
            end_ms=700,
            effect="dereverb",
            strength="strong",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        target = self.store.create_result_path(self.job_dir)

        render_vocal_cleanup(project, target)

        source_audio, source_rate = sf.read(self.source, always_2d=True)
        rendered, rendered_rate = sf.read(target, always_2d=True)
        self.assertEqual(rendered_rate, source_rate)
        self.assertEqual(rendered.shape, source_audio.shape)
        np.testing.assert_allclose(rendered[:17_000], source_audio[:17_000], atol=1e-6)
        np.testing.assert_allclose(rendered[32_000:], source_audio[32_000:], atol=1e-6)
        self.assertGreater(float(np.max(np.abs(rendered[20_000:29_000] - source_audio[20_000:29_000]))), 0.1)

    def _preview_segments(self, prefix: str, frames: int) -> tuple[Path, Path]:
        processed = self.root / f"{prefix}-processed.wav"
        removed = self.root / f"{prefix}-removed.wav"
        samples = np.zeros((frames, 2), dtype=np.float32)
        sf.write(processed, samples, 44_100, subtype="FLOAT")
        sf.write(removed, samples, 44_100, subtype="FLOAT")
        return processed, removed


if __name__ == "__main__":
    unittest.main()
