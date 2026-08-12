from pathlib import Path
import unittest

from scripts.benchmark_separation_candidates import _parse_candidate


class BenchmarkSeparationCandidateTests(unittest.TestCase):
    def test_parse_candidate_supports_windows_drive_paths(self) -> None:
        name, vocals, accompaniment = _parse_candidate(
            r"pair=S:\audio\vocals.wav|S:\audio\instrumental.wav"
        )

        self.assertEqual(name, "pair")
        self.assertEqual(vocals, Path(r"S:\audio\vocals.wav"))
        self.assertEqual(accompaniment, Path(r"S:\audio\instrumental.wav"))

    def test_parse_candidate_rejects_empty_accompaniment(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid candidate paths"):
            _parse_candidate("pair=vocals.wav|")


if __name__ == "__main__":
    unittest.main()
