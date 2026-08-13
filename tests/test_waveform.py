from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from jang_app.services.studio_session import StudioLevelMatchSettings
from jang_app.services.waveform import (
    build_level_matched_waveform_peaks,
    build_waveform_amplitude_peaks,
    build_waveform_peaks,
)


class WaveformTests(unittest.TestCase):
    def test_level_matched_peaks_follow_reference_scale(self) -> None:
        source = np.concatenate((np.full(4, 0.05), np.full(4, 0.4))).astype(np.float32)
        reference = np.concatenate((np.full(4, 0.4), np.full(4, 0.05))).astype(np.float32)
        settings = StudioLevelMatchSettings(
            strength_percent=100,
            response_ms=10,
            max_correction_db=24,
            silence_threshold_db=-80,
        )

        with (
            mock.patch(
                "jang_app.services.waveform._read_soundfile_peaks",
                return_value=source,
            ),
            mock.patch(
                "jang_app.services.waveform._read_rms_envelope",
                side_effect=(source, reference),
            ),
        ):
            peaks = build_level_matched_waveform_peaks(
                Path("source.wav"),
                Path("reference.wav"),
                8,
                settings,
            )

        self.assertGreater(np.mean(peaks[:4]), np.mean(peaks[4:]))
        self.assertAlmostEqual(max(peaks), 0.4, delta=0.06)

    def test_amplitude_peaks_preserve_source_level(self) -> None:
        with mock.patch(
            "jang_app.services.waveform._read_soundfile_peaks",
            return_value=np.asarray([0.1, 0.25, 0.05], dtype=np.float32),
        ):
            peaks = build_waveform_amplitude_peaks(Path("source.wav"), 3)

        self.assertEqual(len(peaks), 3)
        self.assertAlmostEqual(max(peaks), 0.25)

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

    def test_ffmpeg_fallback_keeps_the_remainder_at_the_end_of_the_timeline(self) -> None:
        source = Path("voice.m4a")
        samples = np.zeros(10, dtype=np.float32)
        samples[-1] = 1.0

        with (
            mock.patch("jang_app.services.waveform.sf.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch(
                "jang_app.services.waveform._decode_with_ffmpeg",
                return_value=samples,
            ),
        ):
            peaks = build_waveform_peaks(source, 3)

        self.assertEqual(peaks, [0.0, 0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
