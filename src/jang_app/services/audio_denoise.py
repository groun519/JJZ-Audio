from __future__ import annotations

import math
import os
import uuid
from hashlib import sha256
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR, PREVIEW_WORKSPACE_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


class AudioDenoiseError(RuntimeError):
    """Raised when a non-destructive denoised version cannot be rendered."""


def render_denoised_audio(
    source: Path,
    output_path: Path,
    strength: int,
    sample_start_ms: int = 0,
    sample_end_ms: int = 0,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source_path = source.expanduser().resolve()
    _validate_source(source_path)
    normalized_strength = max(0, min(100, int(strength)))
    duration_ms = max(1, read_audio_metadata(source_path).duration_ms)
    sample_range = _noise_sample_range(sample_start_ms, sample_end_ms, duration_ms)
    return _render_denoised_audio(
        source_path,
        output_path,
        normalized_strength,
        sample_range,
        None,
        duration_ms,
        progress,
    )


def render_denoise_preview(
    source: Path,
    strength: int,
    sample_start_ms: int,
    sample_end_ms: int,
    preview_start_ms: int,
    preview_end_ms: int,
    progress: Callable[[int], None] | None = None,
) -> Path:
    source_path = source.expanduser().resolve()
    _validate_source(source_path)
    duration_ms = max(1, read_audio_metadata(source_path).duration_ms)
    sample_range = _noise_sample_range(sample_start_ms, sample_end_ms, duration_ms)
    preview_range = _preview_range(preview_start_ms, preview_end_ms, duration_ms)
    normalized_strength = max(0, min(100, int(strength)))
    stat = source_path.stat()
    cache_key = sha256(
        "|".join(
            (
                "denoise-preview-v1",
                str(source_path),
                str(stat.st_mtime_ns),
                str(stat.st_size),
                str(normalized_strength),
                str(sample_range),
                str(preview_range),
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    output_path = PREVIEW_WORKSPACE_DIR / "denoise" / f"{cache_key}.wav"
    if output_path.is_file():
        if progress is not None:
            progress(100)
        return output_path
    return _render_denoised_audio(
        source_path,
        output_path,
        normalized_strength,
        sample_range,
        preview_range,
        preview_range[1] - preview_range[0],
        progress,
    )


def _render_denoised_audio(
    source_path: Path,
    output_path: Path,
    strength: int,
    sample_range: tuple[int, int] | None,
    render_range: tuple[int, int] | None,
    duration_ms: int,
    progress: Callable[[int], None] | None,
) -> Path:
    try:
        executable = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise AudioDenoiseError(str(exc)) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(
        f"{output_path.stem}.{uuid.uuid4().hex}.denoising{output_path.suffix}"
    )
    report = _progress_reporter(duration_ms, progress)
    if progress is not None:
        progress(0)
    try:
        command = [
            executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-vn",
            *_denoise_filter_arguments(source_path, strength, sample_range, render_range),
            "-c:a",
            "pcm_s16le",
            "-progress",
            "pipe:1",
            "-nostats",
            str(temporary),
        ]
        completed = run_command(
            command,
            output_callback=report,
        )
        if completed.returncode != 0 or not temporary.is_file():
            raise AudioDenoiseError(f"FFmpeg denoise failed. {completed.output}")
        os.replace(temporary, output_path)
    finally:
        _unlink_quietly(temporary)
    if progress is not None:
        progress(100)
    return output_path


def noise_reduction_db(strength: int) -> float:
    normalized = max(0, min(100, int(strength)))
    return round(max(0.01, normalized * 0.36), 2)


def _denoise_filter_arguments(
    source: Path,
    strength: int,
    sample_range: tuple[int, int] | None,
    render_range: tuple[int, int] | None,
) -> list[str]:
    reduction = noise_reduction_db(strength)
    if sample_range is None:
        filters: list[str] = []
        if render_range is not None:
            start_ms, end_ms = render_range
            filters.extend(
                (
                    f"atrim=start={start_ms / 1000:.3f}:end={end_ms / 1000:.3f}",
                    "asetpts=PTS-STARTPTS",
                )
            )
        filters.append(f"afftdn=nr={reduction:.2f}:nf=-40:tn=1:gs=5")
        return ["-af", ",".join(filters)]

    sample_start_ms, sample_end_ms = sample_range
    sample_duration = (sample_end_ms - sample_start_ms) / 1000
    noise_floor = _estimate_noise_floor(source, sample_start_ms, sample_end_ms)
    main_filter = "asetpts=PTS-STARTPTS"
    if render_range is not None:
        render_start_ms, render_end_ms = render_range
        main_filter = (
            f"atrim=start={render_start_ms / 1000:.3f}:end={render_end_ms / 1000:.3f},"
            "asetpts=PTS-STARTPTS"
        )
    graph = (
        f"[0:a]atrim=start={sample_start_ms / 1000:.3f}:end={sample_end_ms / 1000:.3f},"
        "asetpts=PTS-STARTPTS[sample];"
        f"[0:a]{main_filter}[main];"
        "[sample][main]concat=n=2:v=0:a=1[joined];"
        f"[joined]asendcmd='0.000 afftdn sn start;{sample_duration:.3f} afftdn sn stop',"
        f"afftdn=nr={reduction:.2f}:nf={noise_floor:.1f}:gs=10,"
        f"atrim=start={sample_duration:.3f},asetpts=PTS-STARTPTS[out]"
    )
    return ["-filter_complex", graph, "-map", "[out]"]


def _estimate_noise_floor(source: Path, start_ms: int, end_ms: int) -> float:
    preview_path = prepare_preview_audio(source)
    with sf.SoundFile(preview_path) as audio:
        start_frame = min(audio.frames, round(start_ms * audio.samplerate / 1000))
        end_frame = min(audio.frames, round(end_ms * audio.samplerate / 1000))
        audio.seek(start_frame)
        remaining = max(0, end_frame - start_frame)
        sum_squares = 0.0
        sample_count = 0
        while remaining:
            block = audio.read(min(65536, remaining), always_2d=True, dtype="float32")
            if block.size == 0:
                break
            sum_squares += float(np.sum(np.square(block, dtype=np.float64)))
            sample_count += block.size
            remaining -= len(block)
    rms = math.sqrt(sum_squares / sample_count) if sample_count else 1e-4
    return max(-80.0, min(-20.0, 20 * math.log10(max(rms, 1e-9))))


def _noise_sample_range(start_ms: int, end_ms: int, duration_ms: int) -> tuple[int, int] | None:
    start = max(0, min(int(start_ms), duration_ms))
    end = max(start, min(int(end_ms), duration_ms))
    return (start, end) if end - start >= 100 else None


def _preview_range(start_ms: int, end_ms: int, duration_ms: int) -> tuple[int, int]:
    start = max(0, min(int(start_ms), duration_ms))
    end = max(start, min(int(end_ms), duration_ms))
    if end - start < 100:
        raise AudioDenoiseError("Select at least 0.1 seconds to preview.")
    return (start, end)


def _progress_reporter(
    duration_ms: int,
    progress: Callable[[int], None] | None,
) -> Callable[[str], None]:
    last_value = -1

    def report(line: str) -> None:
        nonlocal last_value
        if progress is None or "=" not in line:
            return
        key, raw_value = line.split("=", 1)
        if key not in {"out_time_us", "out_time_ms"}:
            return
        try:
            position_ms = int(raw_value) // 1000
        except ValueError:
            return
        value = max(0, min(99, round(position_ms * 100 / duration_ms)))
        if value != last_value:
            last_value = value
            progress(value)

    return report


def _validate_source(source: Path) -> None:
    if not source.is_file():
        raise AudioDenoiseError(f"Audio file does not exist: {source}")
    if source.suffix.casefold() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise AudioDenoiseError(f"Unsupported audio format: {source.suffix}")


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
