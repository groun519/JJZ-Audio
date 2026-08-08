from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.command import hidden_subprocess_kwargs
from jang_app.services.environment import require_executable


_FFMPEG_WAVEFORM_SAMPLE_RATE = 800


class WaveformDecodeError(RuntimeError):
    """Raised when neither SoundFile nor FFmpeg can decode an audio source."""


def waveform_cache_key(path: Path, point_count: int) -> tuple[str, int, int, int]:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_mtime_ns, stat.st_size, point_count)


def build_waveform_peaks(path: Path, point_count: int) -> list[float]:
    if point_count <= 0:
        return []

    try:
        peaks = _read_soundfile_peaks(path, point_count)
    except (OSError, RuntimeError):
        samples = _decode_with_ffmpeg(path)
        peaks = _sample_peaks(samples, point_count)

    max_peak = float(np.max(peaks)) if peaks.size else 0.0
    if max_peak <= 0:
        return [0.0 for _ in range(len(peaks))]
    return (peaks / max_peak).tolist()


def _read_soundfile_peaks(path: Path, point_count: int) -> np.ndarray:
    with sf.SoundFile(path) as audio:
        frame_count = len(audio)
        if frame_count <= 0:
            return np.zeros(0, dtype=np.float32)
        bucket_count = min(point_count, frame_count)
        bucket_size = max(1, frame_count // bucket_count)
        return _stream_peaks(audio, bucket_count, bucket_size)


def _decode_with_ffmpeg(path: Path) -> np.ndarray:
    executable = require_executable(
        "ffmpeg",
        "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
        [FFMPEG_BIN_DIR],
    )
    completed = subprocess.run(
        [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path.expanduser().resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(_FFMPEG_WAVEFORM_SAMPLE_RATE),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise WaveformDecodeError(detail or f"FFmpeg could not decode {path.name}.")
    if not completed.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(completed.stdout, dtype="<f4")


def _sample_peaks(samples: np.ndarray, point_count: int) -> np.ndarray:
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    bucket_count = min(point_count, len(samples))
    bucket_size = max(1, len(samples) // bucket_count)
    usable_samples = bucket_count * bucket_size
    buckets = np.abs(samples[:usable_samples]).reshape(bucket_count, bucket_size)
    return np.max(buckets, axis=1).astype(np.float32, copy=False)


def _stream_peaks(audio: sf.SoundFile, bucket_count: int, bucket_size: int) -> np.ndarray:
    peaks = np.zeros(bucket_count, dtype=np.float32)
    usable_frames = bucket_count * bucket_size
    cursor = 0
    while cursor < usable_frames:
        block = audio.read(min(65536, usable_frames - cursor), always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1)
        block_cursor = 0
        while block_cursor < len(mono):
            bucket_index = cursor // bucket_size
            bucket_end = (bucket_index + 1) * bucket_size
            take = min(len(mono) - block_cursor, bucket_end - cursor)
            peaks[bucket_index] = max(
                peaks[bucket_index],
                float(np.max(np.abs(mono[block_cursor : block_cursor + take]))),
            )
            block_cursor += take
            cursor += take
    return peaks
