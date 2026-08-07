from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from jang_app.services.silence_detection import (
    SpeechRegion,
    detect_speech_regions,
    split_regions_at_low_energy,
)


class SilenceDetectionTests(unittest.TestCase):
    def test_detects_separate_voice_regions_with_padding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "phrases.wav"
            _write_levels(source, [(500, 0), (1000, 12000), (700, 0), (800, 9000), (500, 0)])

            regions = detect_speech_regions(
                source,
                threshold_db=-35,
                min_silence_ms=400,
                padding_ms=100,
            )

            self.assertEqual([(region.start_ms, region.end_ms) for region in regions], [(400, 1600), (2100, 3100)])

    def test_merges_voice_across_short_silence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "short-gap.wav"
            _write_levels(source, [(300, 0), (500, 10000), (100, 0), (500, 10000), (300, 0)])

            regions = detect_speech_regions(
                source,
                threshold_db=-35,
                min_silence_ms=300,
                padding_ms=0,
            )

            self.assertEqual([(region.start_ms, region.end_ms) for region in regions], [(300, 1400)])

    def test_returns_no_regions_for_silence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "silence.wav"
            _write_levels(source, [(1000, 0)])

            self.assertEqual(detect_speech_regions(source, threshold_db=-50), ())

    def test_long_region_splits_near_low_energy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "long-phrase.wav"
            _write_levels(source, [(9000, 12000), (2000, 300), (9000, 12000)])

            ranges = split_regions_at_low_energy(
                source,
                (SpeechRegion(0, 20000),),
                max_duration_ms=12000,
            )

            self.assertEqual(len(ranges), 2)
            self.assertGreaterEqual(ranges[0][1], 8500)
            self.assertLessEqual(ranges[0][1], 10500)
            self.assertEqual(ranges[0][1], ranges[1][0])


def _write_levels(path: Path, sections: list[tuple[int, int]]) -> None:
    sample_rate = 8000
    frames = bytearray()
    for duration_ms, amplitude in sections:
        frame_count = round(sample_rate * duration_ms / 1000)
        sample = int(amplitude).to_bytes(2, byteorder="little", signed=True)
        frames.extend(sample * frame_count)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


if __name__ == "__main__":
    unittest.main()
