from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, SUPPORTED_IMAGE_EXTENSIONS
from jang_app.services.audio_export import export_mix
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.app_logging import get_logger
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
from jang_app.services.studio_session import (
    MEDIA_FILL,
    TRACK_VIDEO,
    StudioClip,
    StudioMediaSettings,
    StudioSession,
)
from jang_app.services.video_source import VideoSource
from jang_app.services.video_export_settings import (
    MIN_TARGET_VIDEO_BITRATE_KBPS,
    VideoEncodingPlan,
    VideoExportSettings,
    video_encoding_plan,
)
from jang_app.services.video_quality_optimizer import (
    VideoSampleWindow,
    adaptive_resolution_candidates,
    best_scored_resolution,
    parse_ssim_score,
    parse_vmaf_score,
    representative_video_windows,
)


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
    media: StudioMediaSettings
    source_audio_enabled: bool = False


def can_render_song_video(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
) -> bool:
    """Return whether the renderer can resolve at least one local visual source."""
    if _resolved_timeline_clips(package, session):
        return True
    fallback = source.path.expanduser().resolve() if source.path is not None else None
    return fallback is not None and fallback.is_file()


def render_song_video(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
    progress: Callable[[int], None] | None = None,
    settings: VideoExportSettings | None = None,
) -> Path:
    resolved_settings = settings or VideoExportSettings()
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
        resolved_settings.output_label,
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
            try:
                encoding_plan = video_encoding_plan(
                    resolved_settings,
                    duration_ms / 1000,
                )
            except ValueError as exc:
                raise SongVideoExportError(str(exc)) from exc
            if encoding_plan.is_size_targeted:
                _render_size_targeted_video(
                    executable,
                    visual_clips,
                    mix_path,
                    temporary_output,
                    duration_ms,
                    encoding_plan,
                    Path(temporary),
                    progress,
                )
            else:
                completed = run_command(
                    _render_command(
                        executable,
                        visual_clips,
                        mix_path,
                        temporary_output,
                        duration_ms,
                        encoding_plan.settings,
                    ),
                    output_callback=_ffmpeg_progress(duration_ms, progress),
                )
                if completed.returncode != 0 or not temporary_output.is_file():
                    raise SongVideoExportError(
                        f"FFmpeg video render failed. {completed.output}"
                    )
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
    settings: VideoExportSettings | None = None,
    *,
    video_bitrate_kbps: int | None = None,
    pass_number: int | None = None,
    pass_log_path: Path | None = None,
    include_audio: bool = True,
) -> list[str]:
    resolved_settings = settings or VideoExportSettings()
    command = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    command.extend(_visual_input_args(visual_clips, resolved_settings.frame_rate))
    audio_index = len(visual_clips)
    command.extend(("-i", str(mix_path)))
    command.extend(
        (
            "-filter_complex",
            _render_filter(
                visual_clips,
                duration_ms,
                audio_index,
                resolved_settings,
                include_audio=include_audio,
            ),
            "-map",
            f"[visual{len(visual_clips)}]",
        )
    )
    if include_audio:
        command.extend(("-map", _audio_map(visual_clips, audio_index)))
    command.extend([
        "-t",
        _seconds(duration_ms),
        "-c:v",
        "libx264",
        "-preset",
        resolved_settings.encoding_preset,
    ])
    if video_bitrate_kbps is None:
        command.extend(("-crf", str(resolved_settings.quality_crf)))
    else:
        command.extend(("-b:v", f"{video_bitrate_kbps}k"))
    if pass_number is not None:
        command.extend(("-pass", str(pass_number)))
        if pass_log_path is not None:
            command.extend(("-passlogfile", str(pass_log_path)))
    command.extend(("-pix_fmt", "yuv420p"))
    if include_audio:
        command.extend(
            (
                "-c:a",
                "aac",
                "-b:a",
                f"{resolved_settings.audio_bitrate_kbps}k",
                "-movflags",
                "+faststart",
            )
        )
    else:
        command.append("-an")
    command.extend(("-progress", "pipe:1", "-nostats", str(output_path)))
    return command


def _visual_input_args(
    visual_clips: tuple[_VisualClip, ...],
    frame_rate: int,
) -> list[str]:
    args: list[str] = []
    for clip in visual_clips:
        duration = _seconds(clip.duration_ms)
        if clip.media_kind == "image":
            args.extend(("-loop", "1", "-framerate", str(frame_rate), "-t", duration))
        else:
            if clip.source_start_ms > 0:
                args.extend(("-ss", _seconds(clip.source_start_ms)))
            args.extend(("-t", duration))
        args.extend(("-i", str(clip.path)))
    return args


def _select_content_adaptive_settings(
    executable: str,
    visual_clips: tuple[_VisualClip, ...],
    duration_ms: int,
    settings: VideoExportSettings,
    video_bitrate_kbps: int,
    temporary_dir: Path,
    progress: Callable[[int], None] | None,
) -> VideoExportSettings:
    logger = get_logger()
    candidates = adaptive_resolution_candidates(
        (settings.width, settings.height),
        source_pixel_ceiling=_source_pixel_ceiling(executable, visual_clips),
    )
    if len(candidates) == 1:
        return replace(settings, width=candidates[0][0], height=candidates[0][1])

    windows = representative_video_windows(duration_ms)
    reference = temporary_dir / "quality-reference.mp4"
    if progress is not None:
        progress(13)
    reference_result = run_command(
        _analysis_render_command(
            executable,
            visual_clips,
            reference,
            duration_ms,
            settings,
            windows,
            reference_quality=True,
        )
    )
    if reference_result.returncode != 0 or not reference.is_file():
        logger.warning(
            "Adaptive video analysis reference failed; retaining %sx%s. %s",
            candidates[0][0],
            candidates[0][1],
            reference_result.output,
        )
        return replace(settings, width=candidates[0][0], height=candidates[0][1])
    if progress is not None:
        progress(14)

    scores: dict[tuple[int, int], float] = {}
    for index, resolution in enumerate(candidates):
        candidate_settings = replace(settings, width=resolution[0], height=resolution[1])
        candidate = temporary_dir / f"quality-{resolution[1]}p.mp4"
        pass_output = temporary_dir / f"quality-{resolution[1]}p-pass.mp4"
        pass_log = temporary_dir / f"quality-{resolution[1]}p"
        first_pass = run_command(
            _analysis_render_command(
                executable,
                visual_clips,
                pass_output,
                duration_ms,
                candidate_settings,
                windows,
                video_bitrate_kbps=video_bitrate_kbps,
                pass_number=1,
                pass_log_path=pass_log,
            )
        )
        second_pass = run_command(
            _analysis_render_command(
                executable,
                visual_clips,
                candidate,
                duration_ms,
                candidate_settings,
                windows,
                video_bitrate_kbps=video_bitrate_kbps,
                pass_number=2,
                pass_log_path=pass_log,
            )
        )
        if (
            first_pass.returncode == 0
            and second_pass.returncode == 0
            and candidate.is_file()
        ):
            score = _measure_video_quality(
                executable,
                candidate,
                reference,
                (settings.width, settings.height),
            )
            if score is not None:
                scores[resolution] = score
        if progress is not None:
            progress(14 + round((index + 1) * 20 / len(candidates)))

    if not scores:
        logger.warning(
            "Adaptive video quality scoring failed; retaining %sx%s.",
            candidates[0][0],
            candidates[0][1],
        )
        selected = candidates[0]
    else:
        selected = best_scored_resolution(scores)
        logger.info(
            "Adaptive video quality selected %sx%s | bitrate=%sk | scores=%s",
            selected[0],
            selected[1],
            video_bitrate_kbps,
            ", ".join(
                f"{width}x{height}:{score:.3f}"
                for (width, height), score in scores.items()
            ),
        )
    return replace(settings, width=selected[0], height=selected[1])


def _analysis_render_command(
    executable: str,
    visual_clips: tuple[_VisualClip, ...],
    output_path: Path,
    duration_ms: int,
    settings: VideoExportSettings,
    windows: tuple[VideoSampleWindow, ...],
    *,
    reference_quality: bool = False,
    video_bitrate_kbps: int | None = None,
    pass_number: int | None = None,
    pass_log_path: Path | None = None,
) -> list[str]:
    command = [executable, "-y", "-hide_banner", "-loglevel", "error"]
    command.extend(_visual_input_args(visual_clips, settings.frame_rate))
    command.extend(
        (
            "-filter_complex",
            _render_analysis_filter(visual_clips, duration_ms, settings, windows),
            "-map",
            "[analysis]",
            "-t",
            _seconds(sum(window.duration_ms for window in windows)),
            "-c:v",
            "libx264",
            "-preset",
            "medium" if reference_quality else settings.encoding_preset,
        )
    )
    if reference_quality:
        command.extend(("-crf", "8"))
    elif video_bitrate_kbps is not None:
        command.extend(("-b:v", f"{video_bitrate_kbps}k"))
    else:
        command.extend(("-crf", str(settings.quality_crf)))
    if pass_number is not None:
        command.extend(("-pass", str(pass_number)))
        if pass_log_path is not None:
            command.extend(("-passlogfile", str(pass_log_path)))
    command.extend(("-pix_fmt", "yuv420p", "-an", str(output_path)))
    return command


def _measure_video_quality(
    executable: str,
    candidate: Path,
    reference: Path,
    reference_resolution: tuple[int, int],
) -> float | None:
    width, height = reference_resolution
    shared = [
        executable,
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(candidate),
        "-i",
        str(reference),
    ]
    preparation = (
        f"[0:v]scale={width}:{height}:flags=lanczos,format=yuv420p,"
        "settb=AVTB,setpts=PTS-STARTPTS[distorted];"
        "[1:v]format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[reference];"
    )
    vmaf = run_command(
        shared
        + [
            "-lavfi",
            preparation + "[distorted][reference]libvmaf",
            "-f",
            "null",
            "-",
        ]
    )
    score = parse_vmaf_score(vmaf.output) if vmaf.returncode == 0 else None
    if score is not None:
        return score
    ssim = run_command(
        shared
        + [
            "-lavfi",
            preparation + "[distorted][reference]ssim",
            "-f",
            "null",
            "-",
        ]
    )
    return parse_ssim_score(ssim.output) if ssim.returncode == 0 else None


def _source_pixel_ceiling(
    executable: str,
    visual_clips: tuple[_VisualClip, ...],
) -> int | None:
    ffmpeg_path = Path(executable)
    ffprobe_name = "ffprobe.exe" if ffmpeg_path.suffix.casefold() == ".exe" else "ffprobe"
    sibling = ffmpeg_path.with_name(ffprobe_name)
    ffprobe = str(sibling) if sibling.is_file() else ffprobe_name
    pixels: list[int] = []
    for source in dict.fromkeys(clip.path for clip in visual_clips):
        result = run_command(
            (
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(source),
            )
        )
        if result.returncode != 0:
            continue
        try:
            width, height = (int(value) for value in result.stdout.strip().split("x", 1))
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            pixels.append(width * height)
    return max(pixels) if pixels else None


def _render_size_targeted_video(
    executable: str,
    visual_clips: tuple[_VisualClip, ...],
    mix_path: Path,
    output_path: Path,
    duration_ms: int,
    plan: VideoEncodingPlan,
    temporary_dir: Path,
    progress: Callable[[int], None] | None,
) -> None:
    target_size = plan.settings.target_size_bytes
    bitrate = plan.video_bitrate_kbps
    if target_size is None or bitrate is None:
        raise SongVideoExportError("The 10MB video encoding plan is incomplete.")

    selected_settings = _select_content_adaptive_settings(
        executable,
        visual_clips,
        duration_ms,
        plan.settings,
        bitrate,
        temporary_dir,
        progress,
    )
    plan = replace(plan, settings=selected_settings)

    pass_output = temporary_dir / "video-pass-one.mp4"
    pass_log = temporary_dir / "video-pass"
    for attempt in range(2):
        _unlink_quietly(pass_output)
        _unlink_quietly(output_path)
        first_pass = run_command(
            _render_command(
                executable,
                visual_clips,
                mix_path,
                pass_output,
                duration_ms,
                plan.settings,
                video_bitrate_kbps=bitrate,
                pass_number=1,
                pass_log_path=pass_log,
                include_audio=False,
            ),
            output_callback=(
                _ffmpeg_progress(duration_ms, progress, start=36, end=64)
                if attempt == 0
                else None
            ),
        )
        if first_pass.returncode != 0:
            raise SongVideoExportError(
                f"FFmpeg video analysis pass failed. {first_pass.output}"
            )

        second_pass = run_command(
            _render_command(
                executable,
                visual_clips,
                mix_path,
                output_path,
                duration_ms,
                plan.settings,
                video_bitrate_kbps=bitrate,
                pass_number=2,
                pass_log_path=pass_log,
            ),
            output_callback=(
                _ffmpeg_progress(duration_ms, progress, start=64, end=96)
                if attempt == 0
                else None
            ),
        )
        if second_pass.returncode != 0 or not output_path.is_file():
            raise SongVideoExportError(
                f"FFmpeg video render failed. {second_pass.output}"
            )
        actual_size = output_path.stat().st_size
        if actual_size <= target_size:
            return

        adjusted_bitrate = int(bitrate * target_size / actual_size * 0.92)
        if adjusted_bitrate < MIN_TARGET_VIDEO_BITRATE_KBPS:
            break
        bitrate = adjusted_bitrate
        if progress is not None:
            progress(96)

    _unlink_quietly(output_path)
    raise SongVideoExportError("Could not keep the video export under 10 MB.")


def _visual_clips(
    package: SongPackage,
    source: VideoSource,
    session: StudioSession,
    output_duration_ms: int,
) -> tuple[_VisualClip, ...]:
    clips: list[_VisualClip] = []
    for clip, path in _resolved_timeline_clips(package, session):
        remaining = output_duration_ms - clip.timeline_start_ms
        duration_ms = min(clip.duration_ms, remaining)
        if duration_ms <= 0:
            continue
        media_kind = _media_kind(path)
        clips.append(
            _VisualClip(
                path,
                media_kind,
                clip.timeline_start_ms,
                clip.source_start_ms,
                duration_ms,
                clip.media,
                (
                    clip.media.source_audio_enabled
                    and media_kind == "video"
                    and _has_audio_stream(path)
                ),
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
            StudioMediaSettings(),
        ),
    )


def _resolved_timeline_clips(
    package: SongPackage,
    session: StudioSession,
) -> tuple[tuple[StudioClip, Path], ...]:
    media_track = next((track for track in session.tracks if track.role == TRACK_VIDEO), None)
    if media_track is None:
        return ()
    resolved: list[tuple[StudioClip, Path]] = []
    for clip in media_track.clips:
        path = resolve_studio_asset(package, clip.asset)
        if path is not None and clip.duration_ms > 0:
            resolved.append((clip, path))
    return tuple(resolved)


def _render_filter(
    clips: tuple[_VisualClip, ...],
    duration_ms: int,
    audio_index: int,
    settings: VideoExportSettings | None = None,
    *,
    include_audio: bool = True,
) -> str:
    resolved_settings = settings or VideoExportSettings()
    filters = [
        f"color=c=black:s={resolved_settings.width}x{resolved_settings.height}:"
        f"r={resolved_settings.frame_rate}:d={_seconds(duration_ms)}[visual0]"
    ]
    for index, clip in enumerate(clips):
        start = _seconds(clip.timeline_start_ms)
        end = _seconds(clip.timeline_start_ms + clip.duration_ms)
        duration = _seconds(clip.duration_ms)
        width = max(1, round(resolved_settings.width * clip.media.scale_percent / 100))
        height = max(1, round(resolved_settings.height * clip.media.scale_percent / 100))
        aspect_mode = "increase" if clip.media.fit_mode == MEDIA_FILL else "decrease"
        offset_x = clip.media.offset_x_percent * resolved_settings.width / 100
        offset_y = clip.media.offset_y_percent * resolved_settings.height / 100
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio={aspect_mode},"
            f"setsar=1,fps={resolved_settings.frame_rate},"
            f"trim=duration={duration},setpts=PTS-STARTPTS+{start}/TB[media{index}]"
        )
        filters.append(
            f"[visual{index}][media{index}]overlay="
            f"x='(W-w)/2+{offset_x:.3f}':y='(H-h)/2+{offset_y:.3f}':"
            "eof_action=pass:shortest=0:"
            f"enable='between(t\\,{start}\\,{end})'[visual{index + 1}]"
        )
    audio_clips = tuple(
        (index, clip)
        for index, clip in enumerate(clips)
        if clip.source_audio_enabled
    )
    if include_audio and audio_clips:
        filters.append(f"[{audio_index}:a:0]anull[audio0]")
        for mix_index, (input_index, clip) in enumerate(audio_clips, start=1):
            filters.append(
                f"[{input_index}:a:0]atrim=duration={_seconds(clip.duration_ms)},"
                f"asetpts=PTS-STARTPTS,adelay={clip.timeline_start_ms}:all=1"
                f"[mediaaudio{mix_index}]"
            )
            filters.append(
                f"[audio{mix_index - 1}][mediaaudio{mix_index}]"
                "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0"
                f"[audio{mix_index}]"
            )
    return ";".join(filters)


def _render_analysis_filter(
    clips: tuple[_VisualClip, ...],
    duration_ms: int,
    settings: VideoExportSettings,
    windows: tuple[VideoSampleWindow, ...],
) -> str:
    filters = [
        _render_filter(
            clips,
            duration_ms,
            len(clips),
            settings,
            include_audio=False,
        )
    ]
    source = f"visual{len(clips)}"
    if len(windows) == 1:
        window = windows[0]
        filters.append(
            f"[{source}]trim=start={_seconds(window.start_ms)}:"
            f"duration={_seconds(window.duration_ms)},"
            "setpts=PTS-STARTPTS[analysis]"
        )
        return ";".join(filters)

    split_outputs = "".join(f"[samplein{index}]" for index in range(len(windows)))
    filters.append(f"[{source}]split={len(windows)}{split_outputs}")
    for index, window in enumerate(windows):
        filters.append(
            f"[samplein{index}]trim=start={_seconds(window.start_ms)}:"
            f"duration={_seconds(window.duration_ms)},"
            f"setpts=PTS-STARTPTS[sample{index}]"
        )
    samples = "".join(f"[sample{index}]" for index in range(len(windows)))
    filters.append(f"{samples}concat=n={len(windows)}:v=1:a=0[analysis]")
    return ";".join(filters)


def _audio_map(clips: tuple[_VisualClip, ...], audio_index: int) -> str:
    count = sum(clip.source_audio_enabled for clip in clips)
    return f"[audio{count}]" if count else f"{audio_index}:a:0"


def _has_audio_stream(path: Path) -> bool:
    try:
        return read_audio_metadata(path).channels > 0
    except (OSError, RuntimeError, ValueError):
        return False


def _media_kind(path: Path) -> str:
    return "image" if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS else "video"


def _seconds(milliseconds: int) -> str:
    return f"{max(0, milliseconds) / 1000:.3f}"


def _ffmpeg_progress(
    duration_ms: int,
    progress: Callable[[int], None] | None,
    *,
    start: int = 12,
    end: int = 99,
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
        progress(
            max(
                start,
                min(end, start + round(position_ms * (end - start) / duration_ms)),
            )
        )

    return report


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
