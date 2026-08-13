from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.command import CommandResult
from jang_app.services.song_package import SongPackageStore
from jang_app.services.song_video_export import (
    SongVideoExportError,
    _VisualClip,
    _render_command,
    list_song_video_exports,
    render_song_video,
)
from jang_app.services.studio_session import MEDIA_FILL, StudioMediaSettings, StudioSession
from jang_app.services.video_source import VIDEO_KIND_FILE, VideoSource
from jang_app.services.video_export_settings import (
    ENCODING_SLOW,
    PRESET_HIGH_QUALITY,
    VideoExportSettings,
)


class SongVideoExportTests(unittest.TestCase):
    def test_render_command_applies_image_layout_and_video_source_audio(self) -> None:
        image = _VisualClip(
            Path("cover.png"),
            "image",
            1_000,
            0,
            5_000,
            StudioMediaSettings(
                fit_mode=MEDIA_FILL,
                scale_percent=150,
                offset_x_percent=10,
                offset_y_percent=-5,
            ),
        )
        video = _VisualClip(
            Path("source.mp4"),
            "video",
            6_000,
            2_000,
            4_000,
            StudioMediaSettings(source_audio_enabled=True),
            source_audio_enabled=True,
        )

        command = _render_command(
            "ffmpeg",
            (image, video),
            Path("mix.wav"),
            Path("output.mp4"),
            10_000,
        )
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("scale=2880:1620:force_original_aspect_ratio=increase", filter_graph)
        self.assertIn("x='(W-w)/2+192.000'", filter_graph)
        self.assertIn("y='(H-h)/2+-54.000'", filter_graph)
        self.assertIn("adelay=6000:all=1", filter_graph)
        self.assertIn("amix=inputs=2", filter_graph)
        self.assertIn("[audio1]", command)

    def test_render_command_applies_custom_resolution_frame_rate_and_quality(self) -> None:
        image = _VisualClip(
            Path("cover.png"),
            "image",
            0,
            0,
            5_000,
            StudioMediaSettings(scale_percent=125, offset_x_percent=10),
        )
        settings = VideoExportSettings(
            width=1280,
            height=720,
            frame_rate=60,
            quality_crf=16,
            encoding_preset=ENCODING_SLOW,
            audio_bitrate_kbps=256,
        )

        command = _render_command(
            "ffmpeg",
            (image,),
            Path("mix.wav"),
            Path("output.mp4"),
            5_000,
            settings,
        )
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("color=c=black:s=1280x720:r=60", filter_graph)
        self.assertIn("scale=1600:900", filter_graph)
        self.assertIn("x='(W-w)/2+128.000'", filter_graph)
        self.assertEqual(command[command.index("-framerate") + 1], "60")
        self.assertEqual(command[command.index("-preset") + 1], "slow")
        self.assertEqual(command[command.index("-crf") + 1], "16")
        self.assertEqual(command[command.index("-b:a") + 1], "256k")

    def test_renders_the_full_studio_mix_as_the_only_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_output(root)
            video = package.folder / "01_source" / "video" / "source.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            source = VideoSource(kind=VIDEO_KIND_FILE, path=video, original_name=video.name)
            session = StudioSession()
            captured: dict[str, object] = {}
            progress = []

            def fake_export(_sources, output: Path, **options) -> Path:
                captured["mix_options"] = options
                sf.write(output, np.zeros(16_000, dtype=np.float32), 16_000)
                return output

            def fake_command(args, **options):
                captured["command"] = list(args)
                callback = options.get("output_callback")
                if callback is not None:
                    callback("out_time_ms=500000")
                Path(args[-1]).write_bytes(b"rendered")
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.song_video_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.song_video_export.export_mix", side_effect=fake_export):
                    with patch("jang_app.services.song_video_export.run_command", side_effect=fake_command):
                        rendered = render_song_video(package, source, session, progress.append)

            command = captured["command"]
            self.assertEqual(rendered.parent, package.folder / "04_exports" / "video")
            self.assertEqual(rendered.name, "Song - YouTube 1080p.mp4")
            self.assertEqual(rendered.read_bytes(), b"rendered")
            self.assertNotIn("start_ms", captured["mix_options"])
            self.assertNotIn("end_ms", captured["mix_options"])
            self.assertNotIn("-ss", command)
            self.assertEqual(command[command.index("-t") + 1], "1.000")
            self.assertIn("[visual1]", command)
            self.assertIn("1:a:0", command)
            self.assertEqual(progress[-1], 100)
            self.assertEqual(list_song_video_exports(package)[0].path, rendered)

    def test_image_source_is_looped_and_composited_into_the_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_output(root)
            image = package.folder / "01_source" / "video" / "cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"image")
            source = VideoSource(kind=VIDEO_KIND_FILE, path=image, original_name=image.name)
            captured: dict[str, object] = {}

            def fake_export(_sources, output: Path, **_options) -> Path:
                sf.write(output, np.zeros(16_000, dtype=np.float32), 16_000)
                return output

            def fake_command(args, **_options):
                captured["command"] = list(args)
                Path(args[-1]).write_bytes(b"rendered")
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.song_video_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.song_video_export.export_mix", side_effect=fake_export):
                    with patch("jang_app.services.song_video_export.run_command", side_effect=fake_command):
                        render_song_video(package, source, StudioSession())

            command = captured["command"]
            self.assertIn("-loop", command)
            self.assertIn(str(image), command)
            self.assertIn("color=c=black:s=1920x1080", command[command.index("-filter_complex") + 1])

    def test_video_preset_is_reflected_in_the_export_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            image = package.folder / "01_source" / "video" / "cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"image")
            source = VideoSource(kind=VIDEO_KIND_FILE, path=image, original_name=image.name)

            def fake_export(_sources, output: Path, **_options) -> Path:
                sf.write(output, np.zeros(16_000, dtype=np.float32), 16_000)
                return output

            def fake_command(args, **_options):
                Path(args[-1]).write_bytes(b"rendered")
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.song_video_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.song_video_export.export_mix", side_effect=fake_export):
                    with patch("jang_app.services.song_video_export.run_command", side_effect=fake_command):
                        rendered = render_song_video(
                            package,
                            source,
                            StudioSession(),
                            settings=VideoExportSettings(preset_id=PRESET_HIGH_QUALITY),
                        )

            self.assertEqual(rendered.name, "Song - High Quality Video.mp4")

    def test_rejects_a_source_without_a_local_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            with self.assertRaises(SongVideoExportError):
                render_song_video(package, VideoSource(url="https://example.test/video"), StudioSession())

    def test_legacy_timestamp_video_is_renamed_when_exports_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            output_dir = package.folder / "04_exports" / "video"
            output_dir.mkdir(parents=True)
            legacy = output_dir / "video-20260806-160444.mp4"
            legacy.write_bytes(b"video")

            records = list_song_video_exports(package)

            self.assertFalse(legacy.exists())
            self.assertEqual([record.path.name for record in records], ["Song - Video.mp4"])


def _package_with_output(root: Path):
    source = root / "source.wav"
    sf.write(source, np.zeros(16_000, dtype=np.float32), 16_000)
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    package, _created = store.import_audio(source, title="Song")
    output = root / "vocal-output"
    output.mkdir()
    sf.write(output / "vocals.wav", np.zeros(16_000, dtype=np.float32), 16_000)
    sf.write(output / "no_vocals.wav", np.zeros(16_000, dtype=np.float32), 16_000)
    return store.attach_output(package.song_id, output, "Run 01")


if __name__ == "__main__":
    unittest.main()
