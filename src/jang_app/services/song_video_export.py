from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.audio_export import export_mix
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.export_catalog import ExportedFile, list_exported_files
from jang_app.services.song_export import build_song_mix_sources
from jang_app.services.song_package import EXPORT_STAGE, SongPackage
from jang_app.services.studio_session import StudioSession
from jang_app.services.video_source import VideoSource


class SongVideoExportError(RuntimeError):
    """Raised when a Studio video cannot be rendered."""


SongVideoExport = ExportedFile


def render_song_video(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
    progress: Callable[[int], None] | None = None,
) -> Path:
    video_path = source.path.expanduser().resolve() if source.path is not None else None
    if video_path is None or not video_path.is_file():
        raise SongVideoExportError("Download or add a local video before rendering.")
    try:
        executable = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise SongVideoExportError(str(exc)) from exc

    output_dir = song_video_export_dir(package)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = _next_video_path(output_dir)
    temporary_output = output_path.with_name(f"{output_path.stem}.{uuid.uuid4().hex}.rendering.mp4")
    if progress is not None:
        progress(1)

    try:
        with tempfile.TemporaryDirectory(prefix="video-render-", dir=output_dir) as temporary:
            mix_path = Path(temporary) / "studio-mix.wav"
            export_mix(
                build_song_mix_sources(package, session),
                mix_path,
            )
            if progress is not None:
                progress(12)
            duration_ms = max(1, read_audio_metadata(mix_path).duration_ms)
            completed = run_command(
                _render_command(
                    executable,
                    video_path,
                    mix_path,
                    temporary_output,
                    duration_ms,
                ),
                output_callback=_ffmpeg_progress(duration_ms, progress),
            )
            if completed.returncode != 0 or not temporary_output.is_file():
                raise SongVideoExportError(f"FFmpeg video render failed. {completed.output}")
            os.replace(temporary_output, output_path)
    finally:
        _unlink_quietly(temporary_output)

    if progress is not None:
        progress(100)
    return output_path.resolve()


def song_video_export_dir(package: SongPackage) -> Path:
    return package.folder / EXPORT_STAGE / "video"


def list_song_video_exports(package: SongPackage) -> tuple[SongVideoExport, ...]:
    return list_exported_files(song_video_export_dir(package), "*.mp4")


def _render_command(
    executable: str,
    video_path: Path,
    mix_path: Path,
    output_path: Path,
    duration_ms: int,
) -> list[str]:
    return [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-i",
        str(mix_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        f"{duration_ms / 1000:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "320k",
        "-movflags",
        "+faststart",
        "-shortest",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


def _ffmpeg_progress(
    duration_ms: int,
    progress: Callable[[int], None] | None,
) -> Callable[[str], None]:
    def report(line: str) -> None:
        if progress is None or "=" not in line:
            return
        key, value = line.split("=", 1)
        if key not in {"out_time_us", "out_time_ms"}:
            return
        try:
            position_ms = int(value) // 1000
        except ValueError:
            return
        progress(max(12, min(99, 12 + round(position_ms * 87 / duration_ms))))

    return report


def _next_video_path(output_dir: Path) -> Path:
    stem = f"video-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    candidate = output_dir / f"{stem}.mp4"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{suffix:03d}.mp4"
        suffix += 1
    return candidate


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
