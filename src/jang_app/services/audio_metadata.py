from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import soundfile as sf
from mutagen import File as open_mutagen_file

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


@dataclass(frozen=True)
class AudioMetadata:
    duration_ms: int
    sample_rate: int
    channels: int


def read_audio_metadata(path: Path) -> AudioMetadata:
    source = path.expanduser().resolve()
    stat = source.stat()
    return _read_audio_metadata_cached(str(source), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=512)
def _read_audio_metadata_cached(
    source_key: str,
    _modified_ns: int,
    _size: int,
) -> AudioMetadata:
    source = Path(source_key)
    try:
        info = sf.info(source)
        duration_ms = int(info.duration * 1000) if info.duration else 0
        return AudioMetadata(duration_ms=duration_ms, sample_rate=info.samplerate, channels=info.channels)
    except Exception:
        pass
    try:
        return _read_audio_metadata_with_mutagen(source)
    except Exception:
        return _read_audio_metadata_with_ffprobe(source)


def clear_audio_metadata_cache() -> None:
    _read_audio_metadata_cached.cache_clear()


def format_duration(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _read_audio_metadata_with_mutagen(path: Path) -> AudioMetadata:
    audio = open_mutagen_file(path)
    info = getattr(audio, "info", None)
    if info is None:
        raise RuntimeError(f"Could not read audio metadata: {path}")
    duration_ms = round(float(getattr(info, "length", 0.0)) * 1000)
    if duration_ms <= 0:
        raise RuntimeError(f"Audio duration is unavailable: {path}")
    return AudioMetadata(
        duration_ms=duration_ms,
        sample_rate=max(0, int(getattr(info, "sample_rate", 0))),
        channels=max(0, int(getattr(info, "channels", 0))),
    )


def _read_audio_metadata_with_ffprobe(path: Path) -> AudioMetadata:
    try:
        executable = require_executable(
            "ffprobe",
            "Place FFprobe under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise RuntimeError(str(exc)) from exc

    completed = run_command(
        [
            executable,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels:format=duration",
            "-of",
            "default=noprint_wrappers=1",
            str(path),
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.output or f"Could not read audio metadata: {path}")

    values = _parse_ffprobe_output(completed.stdout)
    duration = _float_value(values.get("duration"), 0.0)
    sample_rate = int(_float_value(values.get("sample_rate"), 0.0))
    channels = int(_float_value(values.get("channels"), 0.0))
    return AudioMetadata(duration_ms=int(duration * 1000), sample_rate=sample_rate, channels=channels)


def _parse_ffprobe_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _float_value(value: str | None, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback
