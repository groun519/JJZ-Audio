from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services import output_catalog
from jang_app.services.output_catalog import load_output_sound_set, scan_output_sound_sets


class OutputCatalogTests(unittest.TestCase):
    def test_scan_only_checks_wav_files_once_per_result_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "nested" / "second"
            ignored = root / "unrelated"
            for job_dir in (first, second):
                job_dir.mkdir(parents=True)
                (job_dir / "vocals.wav").write_bytes(b"vocals")
                (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            ignored.mkdir()
            for index in range(20):
                (ignored / f"artifact-{index}.bin").write_bytes(b"ignored")

            with patch.object(
                output_catalog,
                "_job_wav_files",
                wraps=output_catalog._job_wav_files,
            ) as wav_files:
                sound_sets = scan_output_sound_sets(root)

            self.assertEqual({item.job_dir for item in sound_sets}, {first, second})
            self.assertEqual(wav_files.call_count, 2)

    def test_discovers_descriptive_and_compact_rvc_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_dir = root / "run"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "no_vocals.wav").write_bytes(b"instrumental")
            descriptive = job_dir / "vocals_rvc_voice_pitch_p0_noindex_rmvpe.wav"
            compact = job_dir / "rvc_p0_0123456789.wav"
            unrelated = job_dir / "preview.wav"
            descriptive.write_bytes(b"descriptive")
            compact.write_bytes(b"compact")
            unrelated.write_bytes(b"preview")

            sound_set = load_output_sound_set(job_dir, root)

            self.assertIsNotNone(sound_set)
            self.assertEqual(
                set(sound_set.converted_vocal_paths),
                {descriptive.resolve(), compact.resolve()},
            )


if __name__ == "__main__":
    unittest.main()
