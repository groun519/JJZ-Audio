from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request

from jang_app.services.google_drive import (
    DRIVE_MODEL_WORK_FOLDER,
    GoogleDriveClient,
    GoogleDriveError,
    GoogleDriveStorageError,
    GoogleDriveUnavailableError,
    UPLOAD_CHUNK_SIZE,
    _category_folder,
)
from jang_app.services.google_oauth import HttpResponse


class _DriveRequester:
    def __init__(self, quota_limit: int, quota_usage: int = 0) -> None:
        self.quota_limit = quota_limit
        self.quota_usage = quota_usage
        self.requests: list[Request] = []
        self.folder_creations = 0
        self.uploaded = 0

    def __call__(self, request: Request, _timeout: float) -> HttpResponse:
        self.requests.append(request)
        url = request.full_url
        method = request.get_method()
        if "/about?" in url:
            return _json_response(
                {
                    "storageQuota": {
                        "limit": str(self.quota_limit),
                        "usage": str(self.quota_usage),
                        "usageInDrive": "0",
                    }
                }
            )
        if "/drive/v3/files?" in url and method == "GET":
            return _json_response({"files": []})
        if "/drive/v3/files?" in url and method == "POST" and "uploadType" not in url:
            self.folder_creations += 1
            return _json_response({"id": f"folder-{self.folder_creations}"})
        if "uploadType=resumable" in url:
            return HttpResponse(200, {"Location": "https://upload.test/session"}, b"")
        if url == "https://upload.test/session":
            chunk = request.data or b""
            start = self.uploaded
            self.uploaded += len(chunk)
            total = int(request.headers["Content-range"].split("/")[-1])
            if self.uploaded < total:
                return HttpResponse(308, {"Range": f"bytes=0-{self.uploaded - 1}"}, b"")
            return _json_response(
                {
                    "id": "file-id",
                    "name": "shared.zip",
                    "size": str(total),
                    "webViewLink": "https://drive.google.com/file/d/file-id/view",
                    "webContentLink": "https://drive.google.com/uc?id=file-id",
                }
            )
        if "/permissions" in url:
            return _json_response({"id": "permission-id"})
        if "/files/file-id?" in url:
            return _json_response(
                {
                    "id": "file-id",
                    "name": "shared.zip",
                    "size": str(self.uploaded),
                    "webViewLink": "https://drive.google.com/file/d/file-id/view",
                    "webContentLink": "https://drive.google.com/uc?id=file-id",
                }
            )
        return HttpResponse(404, {}, b"{}")


class _RecoveringDriveRequester(_DriveRequester):
    def __init__(self, quota_limit: int) -> None:
        super().__init__(quota_limit)
        self.interrupted = False

    def __call__(self, request: Request, timeout: float) -> HttpResponse:
        if request.full_url == "https://upload.test/session":
            content_range = request.get_header("Content-range", "")
            if content_range.startswith("bytes */"):
                self.requests.append(request)
                return HttpResponse(
                    308,
                    {"Range": f"bytes=0-{self.uploaded - 1}"},
                    b"",
                )
            if not self.interrupted:
                self.requests.append(request)
                self.interrupted = True
                self.uploaded += len(request.data or b"")
                raise RuntimeError("connection reset after server accepted the chunk")
        return super().__call__(request, timeout)


class GoogleDriveTests(unittest.TestCase):
    def test_disabled_drive_api_is_reported_as_unavailable(self) -> None:
        def request(_request: Request, _timeout: float) -> HttpResponse:
            return HttpResponse(
                403,
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "error": {
                            "message": "Google Drive API has not been used in this project.",
                            "errors": [{"reason": "accessNotConfigured"}],
                        }
                    }
                ).encode("utf-8"),
            )

        client = GoogleDriveClient(lambda _refresh: "access-token", requester=request)

        with self.assertRaises(GoogleDriveUnavailableError):
            client.storage_quota()

    def test_resumable_upload_reports_progress_and_creates_public_link(self) -> None:
        size = UPLOAD_CHUNK_SIZE + 17
        requester = _DriveRequester(size * 10)
        progress: list[int] = []
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "shared.zip"
            source.write_bytes(b"x" * size)
            client = GoogleDriveClient(lambda _refresh: "access-token", requester=requester)

            result = client.upload_shared_file(source, "models", progress=progress.append)

        self.assertEqual(result.file_id, "file-id")
        self.assertEqual(result.share_link, "https://drive.google.com/file/d/file-id/view")
        self.assertEqual(requester.uploaded, size)
        self.assertEqual(progress[-1], 100)
        self.assertTrue(any("/permissions" in request.full_url for request in requester.requests))

    def test_upload_stops_before_folder_creation_when_quota_is_too_small(self) -> None:
        requester = _DriveRequester(100, 95)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "shared.zip"
            source.write_bytes(b"123456")
            client = GoogleDriveClient(lambda _refresh: "access-token", requester=requester)

            with self.assertRaises(GoogleDriveStorageError):
                client.upload_shared_file(source, "models")

        self.assertEqual(requester.folder_creations, 0)

    def test_upload_resumes_from_server_offset_after_connection_loss(self) -> None:
        size = UPLOAD_CHUNK_SIZE + 23
        requester = _RecoveringDriveRequester(size * 10)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "shared.zip"
            source.write_bytes(b"x" * size)
            client = GoogleDriveClient(
                lambda _refresh: "access-token",
                requester=requester,
                sleep=lambda _seconds: None,
            )

            result = client.upload_shared_file(source, "models")

        self.assertEqual(result.file_id, "file-id")
        self.assertEqual(requester.uploaded, size)
        self.assertTrue(requester.interrupted)

    def test_empty_file_is_rejected_before_quota_request(self) -> None:
        requester = _DriveRequester(100)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty.wav"
            source.touch()
            client = GoogleDriveClient(lambda _refresh: "access-token", requester=requester)

            with self.assertRaisesRegex(GoogleDriveError, "Empty files"):
                client.upload_shared_file(source, "exports")

        self.assertEqual(requester.requests, [])

    def test_model_work_category_maps_to_dedicated_drive_folder(self) -> None:
        self.assertEqual(_category_folder("model_work"), DRIVE_MODEL_WORK_FOLDER)
        self.assertEqual(_category_folder("MODEL_WORK"), DRIVE_MODEL_WORK_FOLDER)

    def test_delete_file_uses_drive_delete_endpoint(self) -> None:
        requests: list[Request] = []

        def request(value: Request, _timeout: float) -> HttpResponse:
            requests.append(value)
            return HttpResponse(204, {}, b"")

        client = GoogleDriveClient(lambda _refresh: "access-token", requester=request)

        client.delete_file("file-id")

        self.assertEqual(requests[0].get_method(), "DELETE")
        self.assertTrue(requests[0].full_url.endswith("/files/file-id"))

    def test_delete_file_accepts_already_missing_remote(self) -> None:
        client = GoogleDriveClient(
            lambda _refresh: "access-token",
            requester=lambda _request, _timeout: HttpResponse(404, {}, b"{}"),
        )

        client.delete_file("missing-id")


def _json_response(data: dict[str, object]) -> HttpResponse:
    return HttpResponse(200, {"Content-Type": "application/json"}, json.dumps(data).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
