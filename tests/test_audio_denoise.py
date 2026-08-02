from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.audio_denoise import noise_reduction_db, render_denoised_audio
from jang_app.services.command import CommandResult


class AudioDenoiseTests(unittest.TestCase):
    def test_strength_maps_to_bounded_noise_reduction(self) -> None:
        self.assertEqual(noise_reduction_db(-10), 0.01)
        self.assertEqual(noise_reduction_db(50), 18.0)
        self.assertEqual(noise_reduction_db(120), 36.0)

    def test_render_uses_adaptive_ffmpeg_filter_and_atomic_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "voice.wav"
            source.write_bytes(b"source")
            output = root / "processed" / "voice.wav"
            captured: list[str] = []
            progress: list[int] = []

            def run(args, **_kwargs):
                captured.extend(str(value) for value in args)
                Path(args[-1]).write_bytes(b"denoised")
                return CommandResult(args, 0, "", "")

            with (
                patch("jang_app.services.audio_denoise.require_executable", return_value="ffmpeg"),
                patch(
                    "jang_app.services.audio_denoise.read_audio_metadata",
                    return_value=SimpleNamespace(duration_ms=1000),
                ),
                patch("jang_app.services.audio_denoise._estimate_noise_floor", return_value=-32.0),
                patch("jang_app.services.audio_denoise.run_command", side_effect=run),
            ):
                result = render_denoised_audio(source, output, 50, 0, 500, progress.append)

            self.assertEqual(result.read_bytes(), b"denoised")
            self.assertIn(
                "asendcmd='0.000 afftdn sn start;0.500 afftdn sn stop',"
                "afftdn=nr=18.00:nf=-32.0:gs=10",
                captured,
            )
            self.assertEqual(progress[0], 0)
            self.assertEqual(progress[-1], 100)


if __name__ == "__main__":
    unittest.main()
