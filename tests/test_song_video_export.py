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
    _render_analysis_filter,
    _render_command,
    _select_content_adaptive_settings,
    can_render_song_video,
    list_song_video_exports,
    render_song_video,
)
from jang_app.services.studio_assets import studio_sound_pool
from jang_app.services.studio_session import (
    MEDIA_FILL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioMediaSettings,
    StudioSession,
    StudioTrack,
)
from jang_app.services.video_source import VIDEO_KIND_FILE, VideoSource, VideoSourceStore
from jang_app.services.video_export_settings import (
    ENCODING_SLOW,
    PRESET_DISCORD_10MB,
    PRESET_HIGH_QUALITY,
    VIDEO_TARGET_10MB_BYTES,
    VideoExportSettings,
    video_export_preset,
)
from jang_app.services.video_quality_optimizer import representative_video_windows


class SongVideoExportTests(unittest.TestCase):
    def test_timeline_media_enables_video_render_without_an_active_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            source_file = Path(temporary) / "cover.png"
            source_file.write_bytes(b"image")
            imported = VideoSourceStore().import_file(package, source_file)
            media_asset = next(
                asset for asset in studio_sound_pool(package) if asset.reference.role == TRACK_VIDEO
            )
            clip = StudioClip(
                "media-clip",
                media_asset.reference,
                timeline_start_ms=0,
                source_start_ms=0,
                source_end_ms=5_000,
            )
            session = StudioSession(
                tracks=(StudioTrack("media", "Media", TRACK_VIDEO, clips=(clip,)),)
            )
            VideoSourceStore().clear(package)

            self.assertTrue(can_render_song_video(package, VideoSource(), session))
            self.assertTrue(imported.path is not None and imported.path.is_file())

    def test_missing_timeline_media_does_not_enable_video_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            clip = StudioClip(
                "missing-media",
                StudioAssetRef("missing", TRACK_VIDEO, "missing.png"),
                timeline_start_ms=0,
                source_start_ms=0,
                source_end_ms=5_000,
            )
            session = StudioSession(
                tracks=(StudioTrack("media", "Media", TRACK_VIDEO, clips=(clip,)),)
            )

            self.assertFalse(can_render_song_video(package, VideoSource(), session))

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

    def test_size_targeted_render_command_uses_two_pass_bitrate_mode(self) -> None:
        image = _VisualClip(
            Path("cover.png"),
            "image",
            0,
            0,
            5_000,
            StudioMediaSettings(),
        )
        settings = video_export_preset(PRESET_DISCORD_10MB)

        first_pass = _render_command(
            "ffmpeg",
            (image,),
            Path("mix.wav"),
            Path("pass-one.mp4"),
            5_000,
            settings,
            video_bitrate_kbps=400,
            pass_number=1,
            pass_log_path=Path("pass-log"),
            include_audio=False,
        )
        second_pass = _render_command(
            "ffmpeg",
            (image,),
            Path("mix.wav"),
            Path("output.mp4"),
            5_000,
            settings,
            video_bitrate_kbps=400,
            pass_number=2,
            pass_log_path=Path("pass-log"),
        )

        self.assertNotIn("-crf", first_pass)
        self.assertEqual(first_pass[first_pass.index("-b:v") + 1], "400k")
        self.assertEqual(first_pass[first_pass.index("-pass") + 1], "1")
        self.assertIn("-an", first_pass)
        self.assertNotIn("-b:a", first_pass)
        self.assertEqual(second_pass[second_pass.index("-pass") + 1], "2")
        self.assertIn("-b:a", second_pass)

    def test_adaptive_quality_selects_the_highest_scoring_candidate(self) -> None:
        image = _VisualClip(
            Path("cover.png"),
            "image",
            0,
            0,
            180_000,
            StudioMediaSettings(),
        )
        settings = video_export_preset(PRESET_DISCORD_10MB)
        progress: list[int] = []
        scores = {"1080p": 82.0, "960p": 91.5, "720p": 95.0, "480p": 89.0}

        def fake_command(args, **_options):
            command = list(args)
            if "-lavfi" in command:
                candidate = Path(command[command.index("-i") + 1]).stem
                label = next(label for label in scores if label in candidate)
                return CommandResult(args, 0, "", f"VMAF score: {scores[label]:.6f}")
            Path(command[-1]).write_bytes(b"video")
            return CommandResult(args, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "jang_app.services.song_video_export._source_pixel_ceiling",
                return_value=None,
            ):
                with patch(
                    "jang_app.services.song_video_export.run_command",
                    side_effect=fake_command,
                ):
                    selected = _select_content_adaptive_settings(
                        "ffmpeg",
                        (image,),
                        180_000,
                        settings,
                        294,
                        Path(temporary),
                        progress.append,
                    )

        self.assertEqual((selected.width, selected.height), (1280, 720))
        self.assertEqual(progress[-1], 34)

    def test_analysis_filter_concatenates_representative_timeline_windows(self) -> None:
        image = _VisualClip(
            Path("cover.png"),
            "image",
            0,
            0,
            180_000,
            StudioMediaSettings(),
        )

        graph = _render_analysis_filter(
            (image,),
            180_000,
            video_export_preset(PRESET_DISCORD_10MB),
            representative_video_windows(180_000),
        )

        self.assertIn("[visual1]split=3", graph)
        self.assertIn("concat=n=3:v=1:a=0[analysis]", graph)

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

    def test_10mb_video_preset_runs_two_passes_and_keeps_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            image = package.folder / "01_source" / "video" / "cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"image")
            source = VideoSource(kind=VIDEO_KIND_FILE, path=image, original_name=image.name)
            commands: list[list[str]] = []
            settings = video_export_preset(PRESET_DISCORD_10MB)

            def fake_export(_sources, output: Path, **_options) -> Path:
                sf.write(output, np.zeros(16_000, dtype=np.float32), 16_000)
                return output

            def fake_command(args, **_options):
                commands.append(list(args))
                Path(args[-1]).write_bytes(b"rendered")
                return CommandResult(args, 0, "", "")

            with patch("jang_app.services.song_video_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.song_video_export.export_mix", side_effect=fake_export):
                    with patch("jang_app.services.song_video_export.run_command", side_effect=fake_command):
                        with patch(
                            "jang_app.services.song_video_export._select_content_adaptive_settings",
                            return_value=settings,
                        ):
                            rendered = render_song_video(
                                package,
                                source,
                                StudioSession(),
                                settings=settings,
                            )

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][commands[0].index("-pass") + 1], "1")
            self.assertEqual(commands[1][commands[1].index("-pass") + 1], "2")
            self.assertLessEqual(rendered.stat().st_size, VIDEO_TARGET_10MB_BYTES)
            self.assertEqual(rendered.name, "Song - Discord 10MB Video.mp4")

    def test_10mb_video_retries_with_a_lower_bitrate_when_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_output(Path(temporary))
            image = package.folder / "01_source" / "video" / "cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"image")
            source = VideoSource(kind=VIDEO_KIND_FILE, path=image, original_name=image.name)
            commands: list[list[str]] = []
            second_passes = 0

            def fake_export(_sources, output: Path, **_options) -> Path:
                sf.write(output, np.zeros(16_000, dtype=np.float32), 16_000)
                return output

            def fake_command(args, **_options):
                nonlocal second_passes
                command = list(args)
                commands.append(command)
                output = Path(command[-1])
                if command[command.index("-pass") + 1] == "2":
                    second_passes += 1
                    output.write_bytes(
                        b"x" * (1_050_000 if second_passes == 1 else 900_000)
                    )
                else:
                    output.write_bytes(b"pass")
                return CommandResult(args, 0, "", "")

            settings = VideoExportSettings(
                preset_id=PRESET_DISCORD_10MB,
                width=854,
                height=480,
                frame_rate=24,
                quality_crf=24,
                encoding_preset=ENCODING_SLOW,
                audio_bitrate_kbps=96,
                target_size_bytes=1_000_000,
            )
            with patch("jang_app.services.song_video_export.require_executable", return_value="ffmpeg"):
                with patch("jang_app.services.song_video_export.export_mix", side_effect=fake_export):
                    with patch("jang_app.services.song_video_export.run_command", side_effect=fake_command):
                        with patch(
                            "jang_app.services.song_video_export._select_content_adaptive_settings",
                            return_value=settings,
                        ):
                            rendered = render_song_video(
                                package,
                                source,
                                StudioSession(),
                                settings=settings,
                            )

            self.assertEqual(len(commands), 4)
            self.assertLessEqual(rendered.stat().st_size, 1_000_000)
            first_bitrate = int(commands[0][commands[0].index("-b:v") + 1][:-1])
            retry_bitrate = int(commands[2][commands[2].index("-b:v") + 1][:-1])
            self.assertLess(retry_bitrate, first_bitrate)

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
