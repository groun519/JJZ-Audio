from __future__ import annotations

import hashlib
import re
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, PREVIEW_WORKSPACE_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


class AudioPreviewError(RuntimeError):
    """Raised when an input audio file cannot be prepared for preview."""


def prepare_preview_audio(source: Path) -> Path:
    audio_path = source.expanduser().resolve()
    _validate_source(audio_path)
    if audio_path.suffix.lower() == ".wav":
        return audio_path

    try:
        executable = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise AudioPreviewError(str(exc)) from exc

    PREVIEW_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    preview_path = PREVIEW_WORKSPACE_DIR / f"{_preview_stem(audio_path)}.wav"
    if _is_fresh_preview(audio_path, preview_path):
        return preview_path

    completed = run_command(
        [
            executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(preview_path),
        ]
    )
    if completed.returncode != 0 or not preview_path.is_file():
        raise AudioPreviewError(f"Could not prepare audio preview. {completed.output}")
    return preview_path


def _validate_source(source: Path) -> None:
    if not source.is_file():
        raise AudioPreviewError(f"Audio file does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise AudioPreviewError(f"Unsupported audio format: {source.suffix}. Supported: {supported}")


def _is_fresh_preview(source: Path, preview_path: Path) -> bool:
    return preview_path.is_file() and preview_path.stat().st_mtime >= source.stat().st_mtime


def _preview_stem(path: Path) -> str:
    digest = hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.stem).strip("_").lower()[:48] or "audio"
    return f"{digest}_{slug}"
