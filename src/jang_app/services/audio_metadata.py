from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

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
    try:
        info = sf.info(source)
        duration_ms = int(info.duration * 1000) if info.duration else 0
        return AudioMetadata(duration_ms=duration_ms, sample_rate=info.samplerate, channels=info.channels)
    except Exception:
        return _read_audio_metadata_with_ffprobe(source)


def format_duration(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _read_audio_metadata_with_ffprobe(path: Path) -> AudioMetadata:
    try:
        require_executable("ffprobe", "Place FFprobe under third_party/ffmpeg/bin or add it to PATH.", [FFMPEG_BIN_DIR])
    except MissingExecutableError as exc:
        raise RuntimeError(str(exc)) from exc

    completed = run_command(
        [
            "ffprobe",
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
