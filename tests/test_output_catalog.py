from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.output_catalog import load_output_sound_set


class OutputCatalogTests(unittest.TestCase):
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
