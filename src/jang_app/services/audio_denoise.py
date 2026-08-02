from __future__ import annotations

import math
import os
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR, SUPPORTED_AUDIO_EXTENSIONS
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
    try:
        executable = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise AudioDenoiseError(str(exc)) from exc

    normalized_strength = max(0, min(100, int(strength)))
    duration_ms = max(1, read_audio_metadata(source_path).duration_ms)
    sample_range = _noise_sample_range(sample_start_ms, sample_end_ms, duration_ms)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(
        f"{output_path.stem}.{uuid.uuid4().hex}.denoising{output_path.suffix}"
    )
    report = _progress_reporter(duration_ms, progress)
    if progress is not None:
        progress(0)
    try:
        completed = run_command(
            [
                executable,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-af",
                _denoise_filter(source_path, normalized_strength, sample_range),
                "-c:a",
                "pcm_s16le",
                "-progress",
                "pipe:1",
                "-nostats",
                str(temporary),
            ],
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


def _denoise_filter(
    source: Path,
    strength: int,
    sample_range: tuple[int, int] | None,
) -> str:
    reduction = noise_reduction_db(strength)
    if sample_range is None:
        return f"afftdn=nr={reduction:.2f}:nf=-40:tn=1:gs=5"
    start_ms, end_ms = sample_range
    noise_floor = _estimate_noise_floor(source, start_ms, end_ms)
    commands = f"{start_ms / 1000:.3f} afftdn sn start;{end_ms / 1000:.3f} afftdn sn stop"
    return f"asendcmd='{commands}',afftdn=nr={reduction:.2f}:nf={noise_floor:.1f}:gs=10"


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
