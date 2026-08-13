from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.drive_share_catalog import DriveShareCatalog
from jang_app.services.google_drive import GoogleDriveFile


class DriveShareCatalogTests(unittest.TestCase):
    def test_share_is_reused_only_while_source_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"first")
            catalog = DriveShareCatalog(root / "shares.json")
            remote = GoogleDriveFile("id", "mix.wav", 5, "https://share", "")
            catalog.record(source, "exports", remote)

            self.assertIsNotNone(catalog.find(source, "exports"))
            source.write_bytes(b"changed")

            self.assertIsNone(catalog.find(source, "exports"))

    def test_remove_clears_matching_share_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("id", "mix.wav", 5, "https://share", ""),
            )

            self.assertTrue(catalog.remove(source, "exports"))
            self.assertIsNone(catalog.find(source, "exports"))
            self.assertFalse(catalog.remove(source, "exports"))

    def test_move_source_preserves_share_after_local_rename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            target = root / "Final Mix.wav"
            source.write_bytes(b"audio")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("id", "mix.wav", 5, "https://share", ""),
            )
            source.rename(target)

            self.assertTrue(catalog.move_source(source, target, "exports"))
            self.assertIsNone(catalog.find(source, "exports"))
            moved = catalog.find(target, "exports")
            self.assertIsNotNone(moved)
            self.assertEqual(moved.share_link, "https://share")


if __name__ == "__main__":
    unittest.main()
