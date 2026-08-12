from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, SUPPORTED_IMAGE_EXTENSIONS
from jang_app.services.audio_export import export_mix
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.export_names import (
    migrate_legacy_song_exports,
    next_song_export_path,
    timestamp_export_pattern,
)
from jang_app.services.export_catalog import ExportedFile, list_exported_files
from jang_app.services.song_export import build_song_mix_sources
from jang_app.services.song_package import EXPORT_STAGE, SongPackage
from jang_app.services.studio_assets import resolve_studio_asset
from jang_app.services.studio_session import TRACK_VIDEO, StudioSession
from jang_app.services.video_source import VideoSource


class SongVideoExportError(RuntimeError):
    """Raised when a Studio video cannot be rendered."""


SongVideoExport = ExportedFile
_LEGACY_VIDEO_PATTERN = timestamp_export_pattern("video", ".mp4")


@dataclass(frozen=True)
class _VisualClip:
    path: Path
    media_kind: str
    timeline_start_ms: int
    source_start_ms: int
    duration_ms: int


def render_song_video(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
    progress: Callable[[int], None] | None = None,
) -> Path:
    try:
        executable = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise SongVideoExportError(str(exc)) from exc

    output_dir = song_video_export_dir(package)
    output_path = next_song_export_path(
        output_dir,
        package.title,
        "Video",
        ".mp4",
    )
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
            visual_clips = _visual_clips(package, source, session, duration_ms)
            if not visual_clips:
                raise SongVideoExportError("Download or add local media before rendering.")
            completed = run_command(
                _render_command(
                    executable,
                    visual_clips,
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
    output_dir = song_video_export_dir(package)
    migrate_legacy_song_exports(
        output_dir,
        package.title,
        "Video",
        ".mp4",
        _LEGACY_VIDEO_PATTERN,
    )
    return list_exported_files(output_dir, "*.mp4")


def _render_command(
    executable: str,
    visual_clips: tuple[_VisualClip, ...],
    mix_path: Path,
    output_path: Path,
    duration_ms: int,
) -> list[str]:
    command = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    for clip in visual_clips:
        duration = _seconds(clip.duration_ms)
        if clip.media_kind == "image":
            command.extend(("-loop", "1", "-framerate", "30", "-t", duration))
        else:
            if clip.source_start_ms > 0:
                command.extend(("-ss", _seconds(clip.source_start_ms)))
            command.extend(("-t", duration))
        command.extend(("-i", str(clip.path)))
    audio_index = len(visual_clips)
    command.extend(("-i", str(mix_path)))
    command.extend(
        (
            "-filter_complex",
            _visual_filter(visual_clips, duration_ms),
            "-map",
            f"[visual{len(visual_clips)}]",
            "-map",
            f"{audio_index}:a:0",
        )
    )
    command.extend([
        "-t",
        _seconds(duration_ms),
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
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ])
    return command


def _visual_clips(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
    output_duration_ms: int,
) -> tuple[_VisualClip, ...]:
    clips: list[_VisualClip] = []
    media_track = next((track for track in session.tracks if track.role == TRACK_VIDEO), None)
    if media_track is not None:
        for clip in media_track.clips:
            path = resolve_studio_asset(package, clip.asset)
            remaining = output_duration_ms - clip.timeline_start_ms
            duration_ms = min(clip.duration_ms, remaining)
            if path is None or duration_ms <= 0:
                continue
            clips.append(
                _VisualClip(
                    path,
                    _media_kind(path),
                    clip.timeline_start_ms,
                    clip.source_start_ms,
                    duration_ms,
                )
            )
    if clips:
        return tuple(sorted(clips, key=lambda clip: clip.timeline_start_ms))

    fallback = source.path.expanduser().resolve() if source.path is not None else None
    if fallback is None or not fallback.is_file():
        return ()
    return (
        _VisualClip(
            fallback,
            _media_kind(fallback),
            0,
            0,
            output_duration_ms,
        ),
    )


def _visual_filter(clips: tuple[_VisualClip, ...], duration_ms: int) -> str:
    filters = [
        f"color=c=black:s=1920x1080:r=30:d={_seconds(duration_ms)}[visual0]"
    ]
    for index, clip in enumerate(clips):
        start = _seconds(clip.timeline_start_ms)
        end = _seconds(clip.timeline_start_ms + clip.duration_ms)
        duration = _seconds(clip.duration_ms)
        filters.append(
            f"[{index}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,"
            f"trim=duration={duration},setpts=PTS-STARTPTS+{start}/TB[media{index}]"
        )
        filters.append(
            f"[visual{index}][media{index}]overlay=eof_action=pass:shortest=0:"
            f"enable='between(t\\,{start}\\,{end})'[visual{index + 1}]"
        )
    return ";".join(filters)


def _media_kind(path: Path) -> str:
    return "image" if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS else "video"


def _seconds(milliseconds: int) -> str:
    return f"{max(0, milliseconds) / 1000:.3f}"


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


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
