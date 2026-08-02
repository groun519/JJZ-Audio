from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from jang_app.services.waveform import build_waveform_peaks


class WaveformTests(unittest.TestCase):
    def test_builds_requested_peaks_without_loading_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "voice.wav"
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes((12000).to_bytes(2, "little", signed=True) * 80000)

            peaks = build_waveform_peaks(source, 2400)

            self.assertEqual(len(peaks), 2400)
            self.assertTrue(all(0.99 <= peak <= 1.0 for peak in peaks))


if __name__ == "__main__":
    unittest.main()
