from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource, export_audio_file, export_mix


class AudioExportTests(unittest.TestCase):
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
