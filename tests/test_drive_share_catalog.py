from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_records_preserve_every_distinct_share(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "shares.json"
            sources = []
            for index in range(24):
                source = root / f"mix-{index}.wav"
                source.write_bytes(f"audio-{index}".encode())
                sources.append(source)

            def record(index: int) -> None:
                DriveShareCatalog(catalog_path).record(
                    sources[index],
                    "exports",
                    GoogleDriveFile(
                        f"id-{index}",
                        sources[index].name,
                        sources[index].stat().st_size,
                        f"https://share/{index}",
                        "",
                    ),
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                tuple(executor.map(record, range(len(sources))))

            records = DriveShareCatalog(catalog_path).records()
            self.assertEqual(len(records), len(sources))
            self.assertEqual(
                {record.file_id for record in records},
                {f"id-{index}" for index in range(len(sources))},
            )

    def test_replacement_atomically_schedules_the_old_remote_for_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mix.wav"
            source.write_bytes(b"first")
            catalog = DriveShareCatalog(root / "shares.json")
            catalog.record(
                source,
                "exports",
                GoogleDriveFile("old-id", source.name, 5, "https://old", ""),
            )
            catalog.remember_pending_remote(
                GoogleDriveFile("new-id", source.name, 6, "", ""),
                "uncommitted upload",
            )
            source.write_bytes(b"second")

            current = catalog.record(
                source,
                "exports",
                GoogleDriveFile("new-id", source.name, 6, "https://new", ""),
            )

            self.assertEqual(current.file_id, "new-id")
            self.assertEqual(catalog.find_target(source, "exports").file_id, "new-id")
            pending = catalog.pending_remote_deletes()
            self.assertEqual([item.file_id for item in pending], ["old-id"])


if __name__ == "__main__":
    unittest.main()
