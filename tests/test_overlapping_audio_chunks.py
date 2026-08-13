from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.overlapping_audio_chunks import (
    audio_requires_chunking,
    stitch_crossfaded_audio_chunks,
    write_overlapping_audio_chunks,
)


class OverlappingAudioChunksTests(unittest.TestCase):
    def test_chunks_and_stitches_to_the_original_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample_rate = 1_000
            source = root / "source.wav"
            timeline = np.linspace(-0.8, 0.8, 3_000, dtype=np.float32)
            sf.write(source, timeline, sample_rate, subtype="FLOAT")

            chunks = write_overlapping_audio_chunks(
                source,
                root / "chunks",
                core_seconds=1.0,
                context_seconds=0.1,
            )
            converted: list[Path] = []
            for chunk in chunks:
                output = chunk.path.with_name(f"c{chunk.index:03d}_o.wav")
                shutil.copy2(chunk.path, output)
                converted.append(output)

            result = stitch_crossfaded_audio_chunks(chunks, converted, root / "result.wav")
            rendered, rendered_rate = sf.read(result, dtype="float32")

            self.assertEqual(len(chunks), 3)
            self.assertEqual(rendered_rate, sample_rate)
            self.assertEqual(len(rendered), len(timeline))
            np.testing.assert_allclose(rendered, timeline, atol=4e-5)

    def test_long_duration_selects_automatic_chunking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.wav"
            sf.write(source, np.zeros(2_000, dtype=np.float32), 1_000, subtype="FLOAT")

            self.assertTrue(
                audio_requires_chunking(
                    source,
                    duration_threshold_seconds=1.0,
                    size_threshold_bytes=1_000_000,
                )
            )
            self.assertFalse(
                audio_requires_chunking(
                    source,
                    duration_threshold_seconds=3.0,
                    size_threshold_bytes=1_000_000,
                )
            )

    def test_all_chunks_use_one_global_peak_normalization_gain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            audio = np.concatenate(
                (
                    np.full(1_000, 0.2, dtype=np.float32),
                    np.full(1_000, 1.2, dtype=np.float32),
                )
            )
            sf.write(source, audio, 1_000, subtype="FLOAT")

            chunks = write_overlapping_audio_chunks(
                source,
                root / "chunks",
                core_seconds=1.0,
                context_seconds=0.0,
                consistent_peak_target=0.95,
            )
            quiet, _ = sf.read(chunks[0].path, dtype="float32")
            loud, _ = sf.read(chunks[1].path, dtype="float32")

            self.assertAlmostEqual(float(np.max(loud)), 0.95, places=5)
            self.assertAlmostEqual(float(np.max(quiet)), 0.2 * 0.95 / 1.2, places=5)
            self.assertAlmostEqual(float(np.max(loud) / np.max(quiet)), 6.0, places=4)

    def test_chunk_boundary_moves_to_nearby_low_energy_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            audio = np.full(2_000, 0.5, dtype=np.float32)
            audio[780:830] = 0.0
            sf.write(source, audio, 1_000, subtype="FLOAT")

            chunks = write_overlapping_audio_chunks(
                source,
                root / "chunks",
                core_seconds=1.0,
                context_seconds=0.1,
                boundary_search_seconds=0.3,
            )

            self.assertEqual(len(chunks), 2)
            self.assertTrue(780 <= chunks[0].core_end_frame <= 830)
            self.assertEqual(chunks[1].core_start_frame, chunks[0].core_end_frame)


if __name__ == "__main__":
    unittest.main()
