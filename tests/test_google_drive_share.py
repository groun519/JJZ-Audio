from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.drive_share_catalog import DriveShareCatalog
from jang_app.services.google_drive import (
    GoogleDriveCancelled,
    GoogleDriveError,
    GoogleDriveFile,
)
from jang_app.services.google_drive_share import GoogleDriveShareService


class GoogleDriveShareServiceTests(unittest.TestCase):
    def test_delete_share_removes_remote_file_and_local_catalog_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("file-id", source.name, 5, "https://share", ""),
            )
            service = GoogleDriveShareService(
                SimpleNamespace(account=SimpleNamespace(email="user@example.com")),
                catalog,
            )
            deleted: list[str] = []
            progress: list[int] = []
            client = SimpleNamespace(delete_file=deleted.append)

            with patch.object(service, "_client", return_value=client):
                removed = service.delete_share(
                    source,
                    "exports",
                    progress=progress.append,
                )

            self.assertTrue(removed)
            self.assertEqual(deleted, ["file-id"])
            self.assertEqual(progress[-1], 100)
            self.assertIsNone(catalog.find(source, "exports"))
            self.assertTrue(source.is_file())

    def test_catalog_failure_rolls_back_the_new_remote_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            service = GoogleDriveShareService(SimpleNamespace(), catalog)
            client = _ShareClient("new-id")

            with patch.object(service, "_client", return_value=client):
                with patch.object(catalog, "record", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        service.share_file(source, "exports")

            self.assertEqual(client.deleted, ["new-id"])
            self.assertEqual(catalog.pending_remote_deletes(), ())
            self.assertIsNone(catalog.find_target(source, "exports"))

    def test_failed_publication_retains_cleanup_when_remote_delete_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            service = GoogleDriveShareService(SimpleNamespace(), catalog)
            client = _ShareClient(
                "new-id",
                publish_error=GoogleDriveError("permission denied"),
                delete_error=GoogleDriveError("network unavailable"),
            )

            with patch.object(service, "_client", return_value=client):
                with self.assertRaisesRegex(GoogleDriveError, "permission denied"):
                    service.share_file(source, "exports")

            self.assertEqual(
                [item.file_id for item in catalog.pending_remote_deletes()],
                ["new-id"],
            )

    def test_cancellation_after_publication_rolls_back_remote_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            cancelled = False

            def cancel_after_publish() -> None:
                nonlocal cancelled
                cancelled = True

            service = GoogleDriveShareService(SimpleNamespace(), catalog)
            client = _ShareClient(
                "new-id",
                after_publish=cancel_after_publish,
            )

            with patch.object(service, "_client", return_value=client):
                with self.assertRaises(GoogleDriveCancelled):
                    service.share_file(
                        source,
                        "exports",
                        cancelled=lambda: cancelled,
                    )

            self.assertEqual(client.deleted, ["new-id"])
            self.assertEqual(catalog.pending_remote_deletes(), ())
            self.assertIsNone(catalog.find_target(source, "exports"))

    def test_replacing_a_changed_share_deletes_the_previous_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"old")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("old-id", source.name, 3, "https://old", ""),
            )
            source.write_bytes(b"changed")
            service = GoogleDriveShareService(SimpleNamespace(), catalog)
            client = _ShareClient("new-id")

            with patch.object(service, "_client", return_value=client):
                result = service.share_file(source, "exports")

            self.assertFalse(result.reused)
            self.assertEqual(result.record.file_id, "new-id")
            self.assertEqual(client.deleted, ["old-id"])
            self.assertEqual(catalog.pending_remote_deletes(), ())

    def test_pending_remote_cleanup_retries_before_reusing_a_share(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("current-id", source.name, 5, "https://current", ""),
            )
            catalog.remember_pending_remote(
                GoogleDriveFile("stale-id", "old.wav", 5, "", ""),
                "replaced share",
            )
            service = GoogleDriveShareService(SimpleNamespace(), catalog)
            client = _ShareClient("unused-id")

            with patch.object(service, "_client", return_value=client):
                result = service.share_file(source, "exports")

            self.assertTrue(result.reused)
            self.assertEqual(client.deleted, ["stale-id"])
            self.assertEqual(catalog.pending_remote_deletes(), ())

    def test_connect_retries_remote_cleanup_left_by_cancelled_upload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.remember_pending_remote(
                GoogleDriveFile("stale-id", "old.wav", 5, "", ""),
                "cancelled upload",
            )
            account = SimpleNamespace(email="user@example.com")
            oauth = SimpleNamespace(
                connect=lambda **_options: account,
                access_token=lambda **_options: "token",
            )
            service = GoogleDriveShareService(oauth, catalog)
            client = _ShareClient("unused-id")

            with patch.object(service, "_client", return_value=client):
                connected = service.connect()

            self.assertIs(connected, account)
            self.assertEqual(client.deleted, ["stale-id"])
            self.assertEqual(catalog.pending_remote_deletes(), ())


class _ShareClient:
    def __init__(
        self,
        file_id: str,
        *,
        publish_error: Exception | None = None,
        delete_error: Exception | None = None,
        after_publish=None,
    ) -> None:
        self.remote = GoogleDriveFile(
            file_id,
            "mix.wav",
            5,
            f"https://share/{file_id}",
            "",
        )
        self.publish_error = publish_error
        self.delete_error = delete_error
        self.after_publish = after_publish
        self.deleted: list[str] = []

    def upload_file(self, _source, _category, *, uploaded=None, **_options):
        if uploaded is not None:
            uploaded(self.remote)
        return self.remote

    def publish_file(self, _file_id: str) -> GoogleDriveFile:
        if self.publish_error is not None:
            raise self.publish_error
        if self.after_publish is not None:
            self.after_publish()
        return self.remote

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)
        if self.delete_error is not None:
            raise self.delete_error


if __name__ == "__main__":
    unittest.main()
