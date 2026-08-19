from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, SUPPORTED_VIDEO_EXTENSIONS
from jang_app.services.app_logging import get_logger
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.file_names import safe_filename_stem
from jang_app.services.youtube_runtime import YouTubeRuntimeError, youtube_dl_runtime_options


class YouTubeVideoDownloadError(RuntimeError):
    """Raised when a YouTube video cannot be materialized locally."""


@dataclass(frozen=True)
class YouTubeVideoDownloadResult:
    url: str
    title: str
    video_path: Path


ProgressCallback = Callable[[int], None]
_VIDEO_FORMAT = (
    "bv*[vcodec^=avc1][ext=mp4][height<=1080]/"
    "bv*[ext=mp4][height<=1080]/bv*/b"
)


def download_youtube_video(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> YouTubeVideoDownloadResult:
    source_url = url.strip()
    if not source_url.lower().startswith(("http://", "https://")):
        raise YouTubeVideoDownloadError("Enter a valid YouTube URL.")
    try:
        ffmpeg = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
        ffprobe = require_executable(
            "ffprobe",
            "Place FFprobe under third_party/ffmpeg/bin or add it to PATH.",
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
    logger = get_logger()
    logger.info("Starting YouTube video download: url=%s output_dir=%s", source_url, target_dir)
    report = _progress_reporter(progress_callback)
    report(1)
    try:
        runtime_options = youtube_dl_runtime_options()
        with tempfile.TemporaryDirectory(prefix="video-download-", dir=target_dir) as temporary:
            download_dir = Path(temporary)
            options = {
                "format": _VIDEO_FORMAT,
                "outtmpl": str(download_dir / "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "windowsfilenames": True,
                "ffmpeg_location": str(FFMPEG_BIN_DIR) if FFMPEG_BIN_DIR.exists() else None,
                "progress_hooks": [_build_progress_hook(report)],
                "postprocessor_hooks": [_build_postprocessor_hook(report)],
                **runtime_options,
            }
            options = {key: value for key, value in options.items() if value is not None}
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(source_url, download=True)
            downloaded = _find_downloaded_video(download_dir)
            downloaded = _ensure_preview_compatible(downloaded, download_dir, ffmpeg, ffprobe)
            report(99)
            title = _info_text(info, "title") or downloaded.stem
            video_id = safe_filename_stem(_info_text(info, "id"), fallback="youtube", max_length=24)
            title_stem = safe_filename_stem(title, fallback="youtube_video", max_length=64)
            target = target_dir / f"{title_stem}_{video_id}.mp4"
            os.replace(downloaded, target)
    except YouTubeRuntimeError as exc:
        raise YouTubeVideoDownloadError(str(exc)) from exc
    except YouTubeVideoDownloadError:
        raise
    except Exception as exc:
        raise YouTubeVideoDownloadError(str(exc)) from exc

    report(100)
    logger.info("YouTube video download complete: video=%s", target)
    return YouTubeVideoDownloadResult(source_url, title, target.resolve())


def _ensure_preview_compatible(
    source: Path,
    output_dir: Path,
    ffmpeg: str,
    ffprobe: str,
) -> Path:
    if source.suffix.casefold() == ".mp4" and _video_codec(ffprobe, source) == ("h264", "yuv420p"):
        return source

    target = output_dir / f"{source.stem}.compatible.mp4"
    completed = run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    if completed.returncode != 0 or not target.is_file():
        raise YouTubeVideoDownloadError(f"FFmpeg video conversion failed. {completed.output}")
    return target


def _video_codec(ffprobe: str, source: Path) -> tuple[str, str]:
    completed = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt",
            "-of",
            "json",
            str(source),
        ]
    )
    if completed.returncode != 0:
        return "", ""
    try:
        data = json.loads(completed.stdout)
        stream = data["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return "", ""
    return str(stream.get("codec_name", "")), str(stream.get("pix_fmt", ""))


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
