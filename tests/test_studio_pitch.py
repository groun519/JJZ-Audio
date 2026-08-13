from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.studio_pitch import (
    STUDIO_CLIP_PITCH_MAX,
    STUDIO_CLIP_PITCH_MIN,
    clamp_studio_clip_pitch,
    prepare_pitch_shifted_audio,
)


class StudioPitchTests(unittest.TestCase):
    def test_pitch_values_are_clamped_to_the_supported_audio_range(self) -> None:
        self.assertEqual(clamp_studio_clip_pitch(-999), STUDIO_CLIP_PITCH_MIN)
        self.assertEqual(clamp_studio_clip_pitch(999), STUDIO_CLIP_PITCH_MAX)
        self.assertEqual(clamp_studio_clip_pitch("12"), 12)
        self.assertEqual(clamp_studio_clip_pitch(None), 0)

    def test_pitch_render_uses_rubberband_and_reuses_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            cache = root / "cache"
            sf.write(source, np.zeros(8_000, dtype=np.float32), 8_000)
            commands: list[tuple[str, ...]] = []

            def fake_run(command):
                commands.append(tuple(command))
                output = Path(command[-1])
                sf.write(output, np.zeros(8_000, dtype=np.float32), 8_000)
                return SimpleNamespace(returncode=0, output="")

            with (
                patch("jang_app.services.studio_pitch.PREVIEW_WORKSPACE_DIR", cache),
                patch("jang_app.services.studio_pitch.require_executable", return_value="ffmpeg"),
                patch("jang_app.services.studio_pitch.run_command", side_effect=fake_run),
            ):
                first = prepare_pitch_shifted_audio(source, 12)
                second = prepare_pitch_shifted_audio(source, 12)

            self.assertEqual(first, second)
            self.assertEqual(len(commands), 1)
            filter_value = commands[0][commands[0].index("-af") + 1]
            self.assertIn("rubberband=pitch=2.000000000000:tempo=1.0", filter_value)


if __name__ == "__main__":
    unittest.main()
