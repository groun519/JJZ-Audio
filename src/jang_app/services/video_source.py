from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from jang_app.config import SUPPORTED_VIDEO_EXTENSIONS
from jang_app.services.file_names import safe_filename_stem
from jang_app.services.managed_files import copy_file_atomic, write_json_atomic
from jang_app.services.song_package import SOURCE_STAGE, STUDIO_STAGE, SongPackage
from jang_app.services.youtube_video_download import download_youtube_video


VIDEO_SOURCE_VERSION = 1
VIDEO_SOURCE_NAME = "video.json"
VIDEO_KIND_FILE = "file"
VIDEO_KIND_URL = "url"
VIDEO_KIND_YOUTUBE = "youtube"


@dataclass(frozen=True)
class VideoSource:
    kind: str = ""
    path: Path | None = None
    url: str = ""
    original_name: str = ""
    updated_at: str = ""
    inherited: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.kind and (self.path is not None or self.url))

    @property
    def display_name(self) -> str:
        if self.original_name:
            return self.original_name
        if self.path is not None:
            return self.path.name
        return self.url


class VideoSourceStore:
    def load(self, package: SongPackage) -> VideoSource:
        path = video_source_state_path(package)
        if not path.is_file():
            return VideoSource()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return VideoSource()
        if (
            not isinstance(data, dict)
            or data.get("version") != VIDEO_SOURCE_VERSION
            or data.get("song_id") not in (None, "", package.song_id)
        ):
            return VideoSource()

        kind = str(data.get("kind", ""))
        if kind == VIDEO_KIND_FILE:
            managed_path = _resolve_package_path(package, data.get("path"))
            if managed_path is None or not managed_path.is_file():
                return VideoSource()
            return VideoSource(
                kind=kind,
                path=managed_path,
                original_name=str(data.get("original_name", "")),
                updated_at=str(data.get("updated_at", "")),
            )
        if kind in {VIDEO_KIND_URL, VIDEO_KIND_YOUTUBE}:
            url = str(data.get("url", "")).strip()
            if not _is_supported_url(url):
                return VideoSource()
            managed_path = _resolve_package_path(package, data.get("path"))
            if managed_path is not None and not managed_path.is_file():
                managed_path = None
            return VideoSource(
                kind=kind,
                path=managed_path,
                url=url,
                original_name=str(data.get("original_name", "")),
                updated_at=str(data.get("updated_at", "")),
            )
        return VideoSource()

    def resolve(self, package: SongPackage) -> VideoSource:
        configured = self.load(package)
        if configured.is_configured:
            return configured
        if package.source_type == "youtube" and _is_supported_url(package.source_url):
            return VideoSource(
                kind=VIDEO_KIND_YOUTUBE,
                url=package.source_url,
                original_name=package.title,
                inherited=True,
            )
        return VideoSource()

    def managed_sources(self, package: SongPackage) -> tuple[VideoSource, ...]:
        video_dir = package.folder / SOURCE_STAGE / "video"
        if not video_dir.is_dir():
            return ()

        active = self.load(package)
        active_path = active.path.resolve() if active.path is not None else None
        sources: list[VideoSource] = []
        try:
            paths = tuple(video_dir.iterdir())
        except OSError:
            return ()
        for path in paths:
            try:
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                    continue
                resolved = path.resolve()
                resolved.relative_to(video_dir.resolve())
                modified_at = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            if active_path == resolved:
                sources.append(active)
                continue
            sources.append(
                VideoSource(
                    kind=VIDEO_KIND_FILE,
                    path=resolved,
                    original_name=_managed_display_name(path),
                    updated_at=datetime.fromtimestamp(
                        modified_at,
                        tz=UTC,
                    ).isoformat(),
                )
            )
        sources.sort(key=lambda source: source.updated_at, reverse=True)
        sources.sort(key=lambda source: source.path != active_path)
        return tuple(sources)

    def select_managed(self, package: SongPackage, path: Path) -> VideoSource:
        selected = path.expanduser().resolve()
        video_dir = (package.folder / SOURCE_STAGE / "video").resolve()
        try:
            selected.relative_to(video_dir)
        except ValueError as exc:
            raise ValueError("Select a video stored with this song.") from exc
        if not selected.is_file() or selected.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise ValueError("Select a supported stored video.")

        active = self.load(package)
        if active.path is not None and active.path.resolve() == selected:
            return active
        video = VideoSource(
            kind=VIDEO_KIND_FILE,
            path=selected,
            original_name=_managed_display_name(selected),
            updated_at=_now(),
        )
        self._save(package, video)
        return video

    def import_file(self, package: SongPackage, source: Path, progress=None) -> VideoSource:
        source = source.expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise ValueError("Select a supported video file.")

        stat = source.stat()
        digest_input = f"{source}|{stat.st_size}|{stat.st_mtime_ns}".casefold().encode("utf-8")
        digest = hashlib.sha256(digest_input).hexdigest()[:12]
        stem = safe_filename_stem(source.stem, fallback="video", max_length=56)
        target = package.folder / SOURCE_STAGE / "video" / f"{stem}__{digest}{source.suffix.lower()}"
        total_bytes = max(1, stat.st_size)
        copy_file_atomic(
            source,
            target,
            progress=(
                (lambda copied: progress(min(99, int(copied * 100 / total_bytes))))
                if progress is not None
                else None
            ),
        )
        video = VideoSource(
            kind=VIDEO_KIND_FILE,
            path=target.resolve(),
            original_name=source.name,
            updated_at=_now(),
        )
        self._save(package, video)
        if progress is not None:
            progress(100)
        return video

    def set_url(self, package: SongPackage, url: str) -> VideoSource:
        value = url.strip()
        if not _is_supported_url(value):
            raise ValueError("Enter a valid HTTP or HTTPS video URL.")
        video = VideoSource(
            kind=VIDEO_KIND_YOUTUBE if _is_youtube_url(value) else VIDEO_KIND_URL,
            url=value,
            original_name=urlparse(value).netloc,
            updated_at=_now(),
        )
        self._save(package, video)
        return video

    def materialize(self, package: SongPackage, progress=None) -> VideoSource:
        source = self.resolve(package)
        if source.kind != VIDEO_KIND_YOUTUBE or not source.url:
            raise ValueError("A YouTube video source is required.")
        result = download_youtube_video(
            source.url,
            package.folder / SOURCE_STAGE / "video",
            progress,
        )
        video = VideoSource(
            kind=VIDEO_KIND_YOUTUBE,
            path=result.video_path,
            url=result.url,
            original_name=result.title,
            updated_at=_now(),
        )
        self._save(package, video)
        return video

    def clear(self, package: SongPackage) -> None:
        self._save(package, VideoSource())

    def _save(self, package: SongPackage, video: VideoSource) -> None:
        managed_path = ""
        if video.path is not None:
            resolved = video.path.expanduser().resolve()
            try:
                managed_path = resolved.relative_to(package.folder.resolve()).as_posix()
            except ValueError as exc:
                raise ValueError("Video source must stay inside its song package.") from exc
        write_json_atomic(
            video_source_state_path(package),
            {
                "version": VIDEO_SOURCE_VERSION,
                "song_id": package.song_id,
                "kind": video.kind,
                "path": managed_path,
                "url": video.url,
                "original_name": video.original_name,
                "updated_at": video.updated_at,
            },
        )


def video_source_state_path(package: SongPackage) -> Path:
    return package.folder / STUDIO_STAGE / VIDEO_SOURCE_NAME


def _resolve_package_path(package: SongPackage, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    resolved = (package.folder / Path(value)).resolve()
    try:
        resolved.relative_to(package.folder.resolve())
    except ValueError:
        return None
    return resolved


def _is_supported_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_youtube_url(value: str) -> bool:
    host = urlparse(value).netloc.casefold().split(":", 1)[0]
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _managed_display_name(path: Path) -> str:
    stem, separator, digest = path.stem.rpartition("__")
    if separator and len(digest) == 12 and all(character in "0123456789abcdef" for character in digest):
        return f"{stem}{path.suffix}"
    return path.name
