from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, PREVIEW_WORKSPACE_DIR
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


STUDIO_CLIP_PITCH_MIN = -48
STUDIO_CLIP_PITCH_MAX = 48
_PITCH_CACHE_VERSION = "v1"
_TRAILING_PADDING_SECONDS = 0.5


class StudioPitchError(RuntimeError):
    """Raised when a non-destructive Studio pitch render cannot be prepared."""


def clamp_studio_clip_pitch(value: object) -> int:
    try:
        pitch = int(value)
    except (TypeError, ValueError, OverflowError):
        pitch = 0
    return max(STUDIO_CLIP_PITCH_MIN, min(STUDIO_CLIP_PITCH_MAX, pitch))


def prepare_pitch_shifted_audio(source: Path, pitch_semitones: int) -> Path:
    """Return a cached, duration-preserving pitch render for an audio source."""
    audio_path = source.expanduser().resolve()
    if not audio_path.is_file():
        raise StudioPitchError(f"Audio file does not exist: {audio_path}")
    pitch = clamp_studio_clip_pitch(pitch_semitones)
    if pitch == 0:
        return audio_path

    try:
        executable = require_executable(
            "ffmpeg",
            "Install the JJZero Audio media runtime before changing clip pitch.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise StudioPitchError(str(exc)) from exc

    PREVIEW_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PREVIEW_WORKSPACE_DIR / _cache_name(audio_path, pitch)
    if _is_fresh(audio_path, output_path):
        return output_path

    temporary = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.rendering.wav"
    )
    pitch_factor = 2.0 ** (pitch / 12.0)
    filter_expression = (
        f"apad=pad_dur={_TRAILING_PADDING_SECONDS},"
        f"rubberband=pitch={pitch_factor:.12f}:tempo=1.0"
    )
    try:
        completed = run_command(
            (
                executable,
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(audio_path),
                "-map",
                "0:a:0",
                "-vn",
                "-af",
                filter_expression,
                "-c:a",
                "pcm_f32le",
                str(temporary),
            )
        )
        if completed.returncode != 0 or not temporary.is_file():
            raise StudioPitchError(
                f"Could not change clip pitch. {completed.output}".strip()
            )
        os.replace(temporary, output_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return output_path


def _cache_name(source: Path, pitch: int) -> str:
    identity = f"{_PITCH_CACHE_VERSION}|{str(source).casefold()}|{pitch:+d}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"studio-pitch-{digest}-{pitch:+d}.wav"


def _is_fresh(source: Path, output: Path) -> bool:
    try:
        return output.is_file() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False
