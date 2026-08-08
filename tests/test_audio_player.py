from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_player import AudioPlayer


class AudioPlayerTests(unittest.TestCase):
    def test_duration_supports_float32_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "float-output.wav"
            sf.write(
                path,
                np.zeros((44_100, 2), dtype=np.float32),
                44_100,
                subtype="FLOAT",
            )

            self.assertEqual(AudioPlayer().duration_ms(path), 1_000)


if __name__ == "__main__":
    unittest.main()
