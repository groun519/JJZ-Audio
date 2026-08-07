from __future__ import annotations

import json
import mimetypes
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request

from jang_app.services.google_oauth import HttpRequester, HttpResponse, request_url


DRIVE_API_ROOT = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_ROOT = "https://www.googleapis.com/upload/drive/v3"
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_ROOT_FOLDER = "JJZero Audio"
DRIVE_MODEL_FOLDER = "Models"
DRIVE_EXPORT_FOLDER = "Exports"
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class GoogleDriveError(RuntimeError):
    """Raised when Google Drive cannot complete an operation."""


class GoogleDriveUnavailableError(GoogleDriveError):
    """Raised when the configured Drive API route must be disabled."""


class GoogleDriveStorageError(GoogleDriveError):
    def __init__(self, required_bytes: int, available_bytes: int) -> None:
        self.required_bytes = max(0, required_bytes)
        self.available_bytes = max(0, available_bytes)
        message = "Google Drive storage quota is full."
        if self.required_bytes > 0:
            message = (
                "Google Drive does not have enough free space "
                f"({_format_bytes(self.required_bytes)} required, "
                f"{_format_bytes(self.available_bytes)} available)."
            )
        super().__init__(message)


class GoogleDriveCancelled(GoogleDriveError):
    """Raised when a Drive transfer is cancelled by the user."""


@dataclass(frozen=True)
class GoogleDriveQuota:
    limit_bytes: int | None
    usage_bytes: int
    drive_usage_bytes: int

    @property
    def available_bytes(self) -> int | None:
        if self.limit_bytes is None:
            return None
        return max(0, self.limit_bytes - self.usage_bytes)

    def can_store(self, size_bytes: int) -> bool:
        available = self.available_bytes
        return available is None or available >= max(0, size_bytes)


@dataclass(frozen=True)
class GoogleDriveFile:
    file_id: str
    name: str
    size_bytes: int
    web_view_link: str
    download_link: str

    @property
    def share_link(self) -> str:
        return self.web_view_link or self.download_link


AccessTokenProvider = Callable[[bool], str]


class GoogleDriveClient:
    def __init__(
        self,
        access_token: AccessTokenProvider,
        *,
        requester: HttpRequester | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._access_token = access_token
        self._request = requester or request_url
        self._sleep = sleep

    def storage_quota(self) -> GoogleDriveQuota:
        data = self._json_request(
            "GET",
            f"{DRIVE_API_ROOT}/about?{urlencode({'fields': 'storageQuota'})}",
            operation="Google Drive capacity check",
        )
        quota = data.get("storageQuota")
        if not isinstance(quota, dict):
            raise GoogleDriveError("Google Drive did not return storage capacity.")
        return GoogleDriveQuota(
            limit_bytes=_optional_nonnegative_int(quota.get("limit")),
            usage_bytes=_nonnegative_int(quota.get("usage")),
            drive_usage_bytes=_nonnegative_int(quota.get("usageInDrive")),
        )

    def upload_shared_file(
        self,
        source: Path,
        category: str,
        *,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> GoogleDriveFile:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise GoogleDriveError(f"File not found: {source}")
        size_bytes = source.stat().st_size
        if size_bytes <= 0:
            raise GoogleDriveError("Empty files cannot be shared with Google Drive.")
        quota = self.storage_quota()
        if not quota.can_store(size_bytes):
            raise GoogleDriveStorageError(size_bytes, quota.available_bytes or 0)

        category_name = _category_folder(category)
        root_id = self._ensure_folder(DRIVE_ROOT_FOLDER, "root")
        parent_id = self._ensure_folder(category_name, root_id)
        file = self._resumable_upload(source, parent_id, progress, cancelled)
        self._create_public_reader_permission(file.file_id)
        return self._get_file(file.file_id)

    def delete_file(self, file_id: str) -> None:
        normalized_id = file_id.strip()
        if not normalized_id:
            raise GoogleDriveError("Google Drive file ID is missing.")
        response = self._authorized_request(
            Request(
                f"{DRIVE_API_ROOT}/files/{quote(normalized_id)}",
                method="DELETE",
            ),
            operation="Google Drive file deletion",
            refresh_on_unauthorized=True,
        )
        if response.status == 404:
            return
        if not 200 <= response.status < 300:
            raise _drive_response_error(response, "Google Drive file deletion")

    def _ensure_folder(self, name: str, parent_id: str) -> str:
        escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
        escaped_parent = parent_id.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{escaped_name}' and mimeType = '{DRIVE_FOLDER_MIME}' "
            f"and '{escaped_parent}' in parents and trashed = false"
        )
        data = self._json_request(
            "GET",
            f"{DRIVE_API_ROOT}/files?{urlencode({'q': query, 'fields': 'files(id,name)', 'pageSize': 10})}",
            operation="Google Drive folder lookup",
        )
        files = data.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, dict) and str(item.get("name", "")) == name:
                    file_id = str(item.get("id", "")).strip()
                    if file_id:
                        return file_id
        created = self._json_request(
            "POST",
            f"{DRIVE_API_ROOT}/files?{urlencode({'fields': 'id'})}",
            body=json.dumps(
                {
                    "name": name,
                    "mimeType": DRIVE_FOLDER_MIME,
                    "parents": [parent_id],
                    "appProperties": {"jjzero": "folder"},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=UTF-8"},
            operation="Google Drive folder creation",
        )
        file_id = str(created.get("id", "")).strip()
        if not file_id:
            raise GoogleDriveError("Google Drive did not return the created folder ID.")
        return file_id

    def _resumable_upload(
        self,
        source: Path,
        parent_id: str,
        progress: Callable[[int], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> GoogleDriveFile:
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        metadata = json.dumps(
            {
                "name": source.name,
                "parents": [parent_id],
                "appProperties": {"jjzero": "shared-file"},
            }
        ).encode("utf-8")
        response = self._authorized_request(
            Request(
                f"{DRIVE_UPLOAD_ROOT}/files?{urlencode({'uploadType': 'resumable', 'fields': _FILE_FIELDS})}",
                data=metadata,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": mime_type,
                    "X-Upload-Content-Length": str(source.stat().st_size),
                },
                method="POST",
            ),
            operation="Google Drive upload preparation",
        )
        if not 200 <= response.status < 300:
            raise _drive_response_error(response, "Google Drive upload preparation")
        session_url = _header(response.headers, "Location")
        if not session_url:
            raise GoogleDriveError("Google Drive did not return an upload session.")

        total = source.stat().st_size
        uploaded = 0
        if progress is not None:
            progress(0)
        with source.open("rb") as handle:
            while uploaded < total:
                if cancelled is not None and cancelled():
                    raise GoogleDriveCancelled("Google Drive upload was cancelled.")
                handle.seek(uploaded)
                chunk = handle.read(min(UPLOAD_CHUNK_SIZE, total - uploaded))
                if not chunk:
                    raise GoogleDriveError("The source file changed during upload.")
                end = uploaded + len(chunk) - 1
                response = self._upload_chunk(
                    session_url,
                    chunk,
                    uploaded,
                    end,
                    total,
                    mime_type,
                    cancelled,
                )
                if response.status in {200, 201}:
                    if progress is not None:
                        progress(100)
                    return _drive_file_from_data(response.json())
                if response.status != 308:
                    raise _drive_response_error(response, "Google Drive upload")
                uploaded = _next_upload_offset(response.headers, uploaded)
                if progress is not None:
                    progress(min(99, int(uploaded * 100 / total)) if total else 99)
        raise GoogleDriveError("Google Drive upload ended without a file result.")

    def _upload_chunk(
        self,
        session_url: str,
        chunk: bytes,
        start: int,
        end: int,
        total: int,
        mime_type: str,
        cancelled: Callable[[], bool] | None,
    ) -> HttpResponse:
        last_response: HttpResponse | None = None
        last_error: Exception | None = None
        for attempt in range(4):
            if cancelled is not None and cancelled():
                raise GoogleDriveCancelled("Google Drive upload was cancelled.")
            try:
                response = self._authorized_request(
                    Request(
                        session_url,
                        data=chunk,
                        headers={
                            "Content-Type": mime_type,
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{total}",
                        },
                        method="PUT",
                    ),
                    operation="Google Drive upload",
                    refresh_on_unauthorized=True,
                    timeout=300,
                )
            except Exception as exc:
                last_error = exc
                try:
                    response = self._query_upload_status(session_url, total)
                except Exception:
                    if attempt == 3:
                        raise GoogleDriveError(
                            f"Google Drive upload connection failed: {exc}"
                        ) from exc
                    self._sleep(2**attempt)
                    continue
            last_response = response
            if response.status in {200, 201}:
                return response
            if response.status == 308:
                if _header(response.headers, "Range"):
                    return response
            elif response.status not in _RETRYABLE_STATUS_CODES:
                return response
            else:
                try:
                    recovery = self._query_upload_status(session_url, total)
                except Exception as exc:
                    last_error = exc
                else:
                    last_response = recovery
                    if recovery.status in {200, 201}:
                        return recovery
                    if recovery.status == 308:
                        if _header(recovery.headers, "Range"):
                            return recovery
                    elif recovery.status not in _RETRYABLE_STATUS_CODES:
                        return recovery
            if attempt < 3:
                self._sleep(2**attempt)
        if last_error is not None:
            raise GoogleDriveError(
                f"Google Drive upload connection could not be recovered: {last_error}"
            ) from last_error
        if last_response is not None and last_response.status in _RETRYABLE_STATUS_CODES:
            raise _drive_response_error(last_response, "Google Drive upload")
        raise GoogleDriveError(
            "Google Drive did not acknowledge the uploaded data after multiple attempts."
        )

    def _query_upload_status(self, session_url: str, total: int) -> HttpResponse:
        return self._authorized_request(
            Request(
                session_url,
                data=b"",
                headers={
                    "Content-Length": "0",
                    "Content-Range": f"bytes */{total}",
                },
                method="PUT",
            ),
            operation="Google Drive upload recovery",
            refresh_on_unauthorized=True,
        )

    def _create_public_reader_permission(self, file_id: str) -> None:
        self._json_request(
            "POST",
            f"{DRIVE_API_ROOT}/files/{quote(file_id)}/permissions",
            body=json.dumps({"type": "anyone", "role": "reader"}).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=UTF-8"},
            operation="Google Drive link sharing",
        )

    def _get_file(self, file_id: str) -> GoogleDriveFile:
        data = self._json_request(
            "GET",
            f"{DRIVE_API_ROOT}/files/{quote(file_id)}?{urlencode({'fields': _FILE_FIELDS})}",
            operation="Google Drive file lookup",
        )
        return _drive_file_from_data(data)

    def _json_request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        operation: str,
    ) -> dict[str, object]:
        response = self._authorized_request(
            Request(url, data=body, headers=dict(headers or {}), method=method),
            operation=operation,
            refresh_on_unauthorized=True,
        )
        if not 200 <= response.status < 300:
            raise _drive_response_error(response, operation)
        try:
            return response.json()
        except Exception as exc:
            raise GoogleDriveError(f"{operation} returned an unreadable response.") from exc

    def _authorized_request(
        self,
        request: Request,
        *,
        operation: str,
        refresh_on_unauthorized: bool = False,
        timeout: float = 90,
    ) -> HttpResponse:
        response = self._request_with_token(
            request,
            force_refresh=False,
            timeout=timeout,
        )
        if response.status == 401 and refresh_on_unauthorized:
            response = self._request_with_token(
                request,
                force_refresh=True,
                timeout=timeout,
            )
        if response.status == 401:
            raise GoogleDriveError(f"{operation} requires reconnecting the Google account.")
        return response

    def _request_with_token(
        self,
        request: Request,
        *,
        force_refresh: bool,
        timeout: float,
    ) -> HttpResponse:
        token = self._access_token(force_refresh)
        authorized = Request(
            request.full_url,
            data=request.data,
            headers={
                key: value
                for key, value in request.header_items()
                if key.casefold() != "authorization"
            },
            method=request.get_method(),
        )
        authorized.add_header("Authorization", f"Bearer {token}")
        return self._request(authorized, timeout)


_FILE_FIELDS = "id,name,size,webViewLink,webContentLink"


def _drive_file_from_data(data: Mapping[str, object]) -> GoogleDriveFile:
    file_id = str(data.get("id", "")).strip()
    if not file_id:
        raise GoogleDriveError("Google Drive did not return a file ID.")
    return GoogleDriveFile(
        file_id=file_id,
        name=str(data.get("name", "")).strip(),
        size_bytes=_nonnegative_int(data.get("size")),
        web_view_link=str(data.get("webViewLink", "")).strip(),
        download_link=str(data.get("webContentLink", "")).strip(),
    )


def _drive_response_error(response: HttpResponse, operation: str) -> GoogleDriveError:
    try:
        data = response.json()
    except Exception:
        data = {}
    error = data.get("error")
    message = ""
    reason = ""
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        errors = error.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    reason = str(item.get("reason", "")).strip()
                    if reason:
                        break
    if reason == "storageQuotaExceeded":
        return GoogleDriveStorageError(0, 0)
    detail = message or reason or f"HTTP {response.status}"
    if reason in {
        "accessNotConfigured",
        "billingNotEnabled",
        "projectDisabled",
        "serviceDisabled",
    }:
        return GoogleDriveUnavailableError(f"{operation} failed: {detail}")
    return GoogleDriveError(f"{operation} failed: {detail}")


def _category_folder(category: str) -> str:
    value = category.strip().casefold()
    if value == "models":
        return DRIVE_MODEL_FOLDER
    if value == "exports":
        return DRIVE_EXPORT_FOLDER
    raise GoogleDriveError(f"Unsupported Google Drive category: {category}")


def _next_upload_offset(headers: Mapping[str, str], fallback: int) -> int:
    value = _header(headers, "Range")
    match = re.search(r"bytes=0-(\d+)", value)
    return int(match.group(1)) + 1 if match else fallback


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return str(value).strip()
    return ""


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return _nonnegative_int(value)


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return ""
