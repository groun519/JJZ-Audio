from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

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

    def test_uses_ffmpeg_when_soundfile_cannot_decode_the_source(self) -> None:
        source = Path("voice.m4a")
        samples = np.array([0.1, -0.2, 0.4, -0.8, 0.2, -0.1], dtype=np.float32)

        with (
            mock.patch("jang_app.services.waveform.sf.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch("jang_app.services.waveform._decode_with_ffmpeg", return_value=samples) as decode,
        ):
            peaks = build_waveform_peaks(source, 3)

        decode.assert_called_once_with(source)
        self.assertEqual(peaks, [0.25, 1.0, 0.25])

    def test_ffmpeg_fallback_preserves_a_silent_waveform(self) -> None:
        source = Path("silent.m4a")

        with (
            mock.patch("jang_app.services.waveform.sf.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch(
                "jang_app.services.waveform._decode_with_ffmpeg",
                return_value=np.zeros(8, dtype=np.float32),
            ),
        ):
            peaks = build_waveform_peaks(source, 4)

        self.assertEqual(peaks, [0.0, 0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
