from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from email.message import Message
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from jang_app.services.file_names import safe_display_filename_stem, unique_display_path
from jang_app.services.google_drive import GoogleDriveCancelled, GoogleDriveError


_DRIVE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_COPY_CHUNK_SIZE = 8 * 1024 * 1024
_SPACE_BUFFER = 64 * 1024 * 1024


class GoogleDriveDownloadError(GoogleDriveError):
    """Raised when a public Google Drive link cannot be downloaded."""


def google_drive_file_id(link: str) -> str:
    value = link.strip()
    if _DRIVE_FILE_ID.fullmatch(value):
        return value
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    if not (host == "drive.google.com" or host.endswith(".drive.google.com")):
        raise GoogleDriveDownloadError("Enter a Google Drive file link.")
    query_id = parse_qs(parsed.query).get("id", ())
    if query_id and _DRIVE_FILE_ID.fullmatch(query_id[0]):
        return query_id[0]
    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("d", "file"):
        try:
            position = parts.index(marker)
        except ValueError:
            continue
        candidates = parts[position + 1 :]
        for candidate in candidates:
            if _DRIVE_FILE_ID.fullmatch(candidate):
                return candidate
    raise GoogleDriveDownloadError("The Google Drive link has no valid file ID.")


def download_public_drive_file(
    link: str,
    output_dir: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    file_id = google_drive_file_id(link)
    parsed = urlsplit(link.strip()) if "://" in link else None
    resource_key = ""
    if parsed is not None:
        resource_key = parse_qs(parsed.query).get("resourcekey", ("",))[0]
    parameters = {"id": file_id, "export": "download", "confirm": "t"}
    if resource_key:
        parameters["resourcekey"] = resource_key
    url = f"https://drive.usercontent.google.com/download?{urlencode(parameters)}"
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    try:
        response = opener.open(Request(url, headers={"User-Agent": "JJZero Audio"}), timeout=90)
    except HTTPError as exc:
        raise GoogleDriveDownloadError(f"Google Drive download failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise GoogleDriveDownloadError(f"Google Drive download failed: {exc.reason}") from exc

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    content_type = response.headers.get_content_type()
    if content_type == "text/html":
        response.close()
        raise GoogleDriveDownloadError(
            "Google Drive did not expose this file for public download. "
            "Set access to anyone with the link."
        )
    size = _content_length(response.headers)
    if size is not None:
        available = shutil.disk_usage(output_dir).free
        required = size + _SPACE_BUFFER
        if available < required:
            response.close()
            raise GoogleDriveDownloadError(
                "Not enough local space to download the shared model "
                f"({_format_bytes(required)} required, {_format_bytes(available)} available)."
            )
    name = _response_filename(response.headers) or f"JJZero Shared Model {file_id[:8]}.zip"
    target = unique_display_path(
        output_dir / f"{safe_display_filename_stem(Path(name).stem, 'JJZero Shared Model')}.zip"
    )
    temporary = target.with_suffix(f"{target.suffix}.downloading")
    downloaded = 0
    try:
        with response, temporary.open("wb") as output:
            while chunk := response.read(_COPY_CHUNK_SIZE):
                if cancelled is not None and cancelled():
                    raise GoogleDriveCancelled("Google Drive download was cancelled.")
                output.write(chunk)
                downloaded += len(chunk)
                if progress is not None and size:
                    progress(min(99, int(downloaded * 100 / size)))
        os.replace(temporary, target)
    except OSError as exc:
        raise GoogleDriveDownloadError(f"Shared model download could not be saved: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    if progress is not None:
        progress(100)
    return target


def _content_length(headers: Message) -> int | None:
    try:
        value = int(headers.get("Content-Length", ""))
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _response_filename(headers: Message) -> str:
    disposition = headers.get("Content-Disposition", "")
    message = Message()
    message["Content-Disposition"] = disposition
    value = message.get_filename() or ""
    return Path(value).name


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return ""
