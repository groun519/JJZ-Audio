from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.audio_denoise import (
    noise_reduction_db,
    render_denoise_preview,
    render_denoised_audio,
)
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
            graph = captured[captured.index("-filter_complex") + 1]
            self.assertIn("[sample][main]concat=n=2:v=0:a=1", graph)
            self.assertIn(
                "asendcmd='0.000 afftdn sn start;0.500 afftdn sn stop',"
                "afftdn=nr=18.00:nf=-32.0:gs=10",
                graph,
            )
            self.assertIn("atrim=start=0.500,asetpts=PTS-STARTPTS[out]", graph)
            self.assertEqual(progress[0], 0)
            self.assertEqual(progress[-1], 100)

    def test_preview_renders_only_requested_range_and_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "voice.wav"
            source.write_bytes(b"source")
            captured: list[str] = []

            def run(args, **_kwargs):
                captured.extend(str(value) for value in args)
                Path(args[-1]).write_bytes(b"preview")
                return CommandResult(args, 0, "", "")

            with (
                patch("jang_app.services.audio_denoise.PREVIEW_WORKSPACE_DIR", root / "previews"),
                patch("jang_app.services.audio_denoise.require_executable", return_value="ffmpeg"),
                patch(
                    "jang_app.services.audio_denoise.read_audio_metadata",
                    return_value=SimpleNamespace(duration_ms=5000),
                ),
                patch("jang_app.services.audio_denoise.run_command", side_effect=run),
            ):
                first = render_denoise_preview(source, 40, 0, 0, 1200, 3200)
                second = render_denoise_preview(source, 40, 0, 0, 1200, 3200)

            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), b"preview")
            self.assertTrue(
                any(
                    "atrim=start=1.200:end=3.200,asetpts=PTS-STARTPTS" in value
                    for value in captured
                )
            )


if __name__ == "__main__":
    unittest.main()
