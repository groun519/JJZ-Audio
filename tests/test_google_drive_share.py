from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.drive_share_catalog import DriveShareCatalog
from jang_app.services.google_drive import GoogleDriveFile
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


if __name__ == "__main__":
    unittest.main()
