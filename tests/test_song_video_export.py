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
    list_song_video_exports,
    render_song_video,
)
from jang_app.services.studio_session import StudioSession
from jang_app.services.video_source import VIDEO_KIND_FILE, VideoSource


class SongVideoExportTests(unittest.TestCase):
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
            self.assertEqual(rendered.name, "Song - Video.mp4")
            self.assertEqual(rendered.read_bytes(), b"rendered")
            self.assertNotIn("start_ms", captured["mix_options"])
            self.assertNotIn("end_ms", captured["mix_options"])
            self.assertNotIn("-ss", command)
            self.assertEqual(command[command.index("-t") + 1], "1.000")
            self.assertIn("0:v:0", command)
            self.assertIn("1:a:0", command)
            self.assertEqual(progress[-1], 100)
            self.assertEqual(list_song_video_exports(package)[0].path, rendered)

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
