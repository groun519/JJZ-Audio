from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import DOWNLOAD_OUTPUT_DIR, FFMPEG_BIN_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.app_logging import get_logger
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.file_names import safe_filename_stem, unique_path
from jang_app.services.youtube_runtime import YouTubeRuntimeError, youtube_dl_runtime_options


class YouTubeDownloadError(RuntimeError):
    """Raised when a YouTube audio download cannot be completed."""


@dataclass(frozen=True)
class YouTubeDownloadResult:
    url: str
    title: str
    audio_path: Path


ProgressCallback = Callable[[int], None]


def download_youtube_audio(
    url: str,
    output_dir: Path = DOWNLOAD_OUTPUT_DIR,
    progress_callback: ProgressCallback | None = None,
) -> YouTubeDownloadResult:
    source_url = url.strip()
    _validate_url(source_url)
    _require_download_tools()

    try:
        import yt_dlp
    except ImportError as exc:
        raise YouTubeDownloadError("yt-dlp is not installed.") from exc

    logger = get_logger()
    target_dir = output_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    def report(value: int) -> None:
        if progress_callback is not None:
            progress_callback(max(0, min(100, value)))

    try:
        runtime_options = youtube_dl_runtime_options()
    except YouTubeRuntimeError as exc:
        raise YouTubeDownloadError(str(exc)) from exc

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "ffmpeg_location": str(FFMPEG_BIN_DIR) if FFMPEG_BIN_DIR.exists() else None,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }
        ],
        "progress_hooks": [_build_progress_hook(report)],
        "postprocessor_hooks": [_build_postprocessor_hook(report)],
        **runtime_options,
    }
    options = {key: value for key, value in options.items() if value is not None}

    logger.info("Starting YouTube audio download: url=%s output_dir=%s", source_url, target_dir)
    report(2)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(source_url, download=True)
    except Exception as exc:
        logger.exception("YouTube audio download failed")
        raise YouTubeDownloadError(str(exc)) from exc

    audio_path = _normalize_downloaded_audio_path(_find_downloaded_audio(target_dir, started_at, info), target_dir, info)
    title = _extract_title(info, audio_path)
    logger.info("YouTube audio download complete: audio=%s", audio_path)
    report(100)
    return YouTubeDownloadResult(source_url, title, audio_path)


def _validate_url(url: str) -> None:
    if not url:
        raise YouTubeDownloadError("Enter a YouTube URL.")
    if not url.lower().startswith(("http://", "https://")):
        raise YouTubeDownloadError("Enter a valid URL.")


def _require_download_tools() -> None:
    try:
        require_executable("ffmpeg", "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.", [FFMPEG_BIN_DIR])
    except MissingExecutableError as exc:
        raise YouTubeDownloadError(str(exc)) from exc


def _build_progress_hook(report: ProgressCallback):
    def handle_progress(data: dict) -> None:
        if data.get("status") == "finished":
            report(88)
            return
        if data.get("status") != "downloading":
            return

        downloaded = data.get("downloaded_bytes") or 0
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        if total:
            report(5 + int(downloaded / total * 80))

    return handle_progress


def _build_postprocessor_hook(report: ProgressCallback):
    def handle_progress(data: dict) -> None:
        if data.get("status") == "started":
            report(90)
        elif data.get("status") == "finished":
            report(96)

    return handle_progress


def _find_downloaded_audio(target_dir: Path, started_at: float, info: object) -> Path:
    candidates = [
        path
        for path in target_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        and path.stat().st_mtime >= started_at - 2
    ]
    if not candidates:
        candidates = _find_downloaded_audio_by_video_id(target_dir, info)
    if not candidates:
        raise YouTubeDownloadError(f"Downloaded audio file was not found in: {target_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _find_downloaded_audio_by_video_id(target_dir: Path, info: object) -> list[Path]:
    if not isinstance(info, dict):
        return []
    video_id = info.get("id")
    if not isinstance(video_id, str) or not video_id.strip():
        return []

    marker = safe_filename_stem(video_id, fallback="youtube")
    return [
        path
        for path in target_dir.iterdir()
        if path.is_file()
        and marker in safe_filename_stem(path.stem, fallback="audio")
        and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]


def _normalize_downloaded_audio_path(audio_path: Path, target_dir: Path, info: object) -> Path:
    safe_stem = _download_stem(info)
    target_path = unique_path(target_dir / f"{safe_stem}{audio_path.suffix.lower()}")
    if audio_path.expanduser().resolve() == target_path.expanduser().resolve():
        return audio_path

    audio_path.rename(target_path)
    return target_path


def _download_stem(info: object) -> str:
    title = _info_text(info, "title")
    video_id = safe_filename_stem(_info_text(info, "id"), fallback="youtube", max_length=24)
    title_stem = safe_filename_stem(title, fallback="youtube_audio", max_length=64)
    return safe_filename_stem(f"{title_stem}_{video_id}", fallback=f"youtube_audio_{video_id}", max_length=92)


def _info_text(info: object, key: str) -> str:
    if not isinstance(info, dict):
        return ""
    value = info.get(key)
    return value.strip() if isinstance(value, str) else ""


def _extract_title(info: object, audio_path: Path) -> str:
    title = _info_text(info, "title")
    if title:
        return title
    return audio_path.stem
