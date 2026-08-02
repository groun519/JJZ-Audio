from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, SUPPORTED_VIDEO_EXTENSIONS
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.file_names import safe_filename_stem


class YouTubeVideoDownloadError(RuntimeError):
    """Raised when a YouTube video cannot be materialized locally."""


@dataclass(frozen=True)
class YouTubeVideoDownloadResult:
    url: str
    title: str
    video_path: Path


ProgressCallback = Callable[[int], None]


def download_youtube_video(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> YouTubeVideoDownloadResult:
    source_url = url.strip()
    if not source_url.lower().startswith(("http://", "https://")):
        raise YouTubeVideoDownloadError("Enter a valid YouTube URL.")
    try:
        require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise YouTubeVideoDownloadError(str(exc)) from exc

    try:
        import yt_dlp
    except ImportError as exc:
        raise YouTubeVideoDownloadError("yt-dlp is not installed.") from exc

    target_dir = output_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    report = _progress_reporter(progress_callback)
    report(1)
    try:
        with tempfile.TemporaryDirectory(prefix="video-download-", dir=target_dir) as temporary:
            download_dir = Path(temporary)
            options = {
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "merge_output_format": "mp4",
                "outtmpl": str(download_dir / "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "windowsfilenames": True,
                "ffmpeg_location": str(FFMPEG_BIN_DIR) if FFMPEG_BIN_DIR.exists() else None,
                "progress_hooks": [_build_progress_hook(report)],
                "postprocessor_hooks": [_build_postprocessor_hook(report)],
            }
            options = {key: value for key, value in options.items() if value is not None}
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(source_url, download=True)
            downloaded = _find_downloaded_video(download_dir)
            title = _info_text(info, "title") or downloaded.stem
            video_id = safe_filename_stem(_info_text(info, "id"), fallback="youtube", max_length=24)
            title_stem = safe_filename_stem(title, fallback="youtube_video", max_length=64)
            target = target_dir / f"{title_stem}_{video_id}{downloaded.suffix.lower()}"
            os.replace(downloaded, target)
    except YouTubeVideoDownloadError:
        raise
    except Exception as exc:
        raise YouTubeVideoDownloadError(str(exc)) from exc

    report(100)
    return YouTubeVideoDownloadResult(source_url, title, target.resolve())


def _progress_reporter(callback: ProgressCallback | None) -> Callable[[int], None]:
    def report(value: int) -> None:
        if callback is not None:
            callback(max(0, min(100, int(value))))

    return report


def _build_progress_hook(report: Callable[[int], None]):
    def handle(data: dict) -> None:
        if data.get("status") == "finished":
            report(88)
            return
        if data.get("status") != "downloading":
            return
        downloaded = data.get("downloaded_bytes") or 0
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        if total:
            report(4 + int(downloaded / total * 80))

    return handle


def _build_postprocessor_hook(report: Callable[[int], None]):
    def handle(data: dict) -> None:
        if data.get("status") == "started":
            report(90)
        elif data.get("status") == "finished":
            report(98)

    return handle


def _find_downloaded_video(directory: Path) -> Path:
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in SUPPORTED_VIDEO_EXTENSIONS
    ]
    if not candidates:
        raise YouTubeVideoDownloadError("Downloaded video file was not found.")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _info_text(info: object, key: str) -> str:
    if not isinstance(info, dict):
        return ""
    value = info.get(key)
    return value.strip() if isinstance(value, str) else ""
