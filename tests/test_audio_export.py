from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource, export_audio_file, export_mix
from jang_app.services.audio_mix_processing import process_mix_source


class AudioExportTests(unittest.TestCase):
    def test_mix_processing_applies_fades_and_constant_power_pan(self) -> None:
        source = np.ones((1_000, 1), dtype=np.float32)

        processed = process_mix_source(
            source,
            1_000,
            fade_in_ms=100,
            fade_out_ms=200,
            pan_percent=100,
        )

        self.assertEqual(processed.shape, (1_000, 2))
        self.assertAlmostEqual(float(processed[0, 1]), 0.0, places=5)
        self.assertGreater(float(processed[100, 1]), 1.3)
        self.assertAlmostEqual(float(processed[-1, 1]), 0.0, places=5)
        self.assertAlmostEqual(float(np.max(np.abs(processed[:, 0]))), 0.0, places=5)
    def test_export_uses_the_same_output_ceiling_as_realtime_playback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            output = root / "mix.wav"
            sf.write(source, np.array([0.8, 0.2], dtype=np.float32), 8000, subtype="FLOAT")

            export_mix(
                (AudioMixSource("One", source), AudioMixSource("Two", source)),
                output,
            )
            mixed, _sample_rate = sf.read(output, dtype="float32")

            self.assertAlmostEqual(float(mixed[0]), 1.0, places=4)
            self.assertAlmostEqual(float(mixed[1]), 0.4, places=3)

    def test_track_export_preserves_display_title_and_uses_numbered_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            source.write_bytes(b"audio")
            output_dir = root / "exports"

            first = export_audio_file("윤하 - Instrumental", source, output_dir)
            second = export_audio_file("윤하 - Instrumental", source, output_dir)

            self.assertEqual(first.name, "윤하 - Instrumental.wav")
            self.assertEqual(second.name, "윤하 - Instrumental (2).wav")


if __name__ == "__main__":
    unittest.main()
