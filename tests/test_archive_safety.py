from __future__ import annotations

import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from jang_app.services.archive_safety import (
    ArchiveSafetyError,
    extraction_target,
    inspect_archive,
)


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_mixed_separator_traversal_from_external_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "traversal.zip"
            portable_name = "model/../../escape.pth"
            windows_name = r"model\..\..\escape.pth"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(portable_name, b"model")
            package.write_bytes(
                package.read_bytes().replace(
                    portable_name.encode("ascii"),
                    windows_name.encode("ascii"),
                )
            )

            with zipfile.ZipFile(package) as archive:
                with self.assertRaisesRegex(ArchiveSafetyError, "unsafe path"):
                    inspect_archive(archive)

    def test_rejects_duplicate_and_case_equivalent_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(duplicate, "w") as archive:
                    archive.writestr("model/voice.pth", b"first")
                    archive.writestr("model/voice.pth", b"second")
            case_collision = root / "case-collision.zip"
            with zipfile.ZipFile(case_collision, "w") as archive:
                archive.writestr("model/Voice.pth", b"first")
                archive.writestr("model/voice.pth", b"second")

            for package in (duplicate, case_collision):
                with self.subTest(package=package.name):
                    with zipfile.ZipFile(package) as archive:
                        with self.assertRaisesRegex(ArchiveSafetyError, "duplicate path"):
                            inspect_archive(archive)

    def test_rejects_windows_absolute_and_reserved_paths(self) -> None:
        unsafe_names = (
            "C:/voice.pth",
            "//server/share/voice.pth",
            "model/CON.pth",
            "model/trailing./voice.pth",
        )
        for unsafe_name in unsafe_names:
            with self.subTest(path=unsafe_name), tempfile.TemporaryDirectory() as directory:
                package = Path(directory) / "unsafe.zip"
                with zipfile.ZipFile(package, "w") as archive:
                    archive.writestr(unsafe_name, b"model")
                with zipfile.ZipFile(package) as archive:
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(archive)

    def test_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "link.zip"
            member = zipfile.ZipInfo("model/link.pth")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(member, b"target")

            with zipfile.ZipFile(package) as archive:
                with self.assertRaisesRegex(ArchiveSafetyError, "link"):
                    inspect_archive(archive)

    def test_rejects_extreme_compression_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "compressed.zip"
            with zipfile.ZipFile(
                package,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                archive.writestr("model/voice.pth", b"0" * (1024 * 1024))

            with zipfile.ZipFile(package) as archive:
                with self.assertRaisesRegex(ArchiveSafetyError, "compression ratio"):
                    inspect_archive(archive)

    def test_enforces_member_file_and_total_size_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "limits.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("model/one.pth", b"1234")
                archive.writestr("model/two.index", b"5678")

            checks = (
                ("MAX_ARCHIVE_MEMBERS", 1, "too many files"),
                ("MAX_ARCHIVE_FILE_SIZE", 3, "file is too large"),
                ("MAX_ARCHIVE_TOTAL_SIZE", 7, "supported size"),
            )
            for constant, value, message in checks:
                with self.subTest(limit=constant), patch(
                    f"jang_app.services.archive_safety.{constant}",
                    value,
                ), zipfile.ZipFile(package) as archive:
                    with self.assertRaisesRegex(ArchiveSafetyError, message):
                        inspect_archive(archive)

    def test_extraction_target_remains_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = extraction_target(root, "model/voice.pth")

            self.assertEqual(target, root / "model" / "voice.pth")
            with self.assertRaises(ArchiveSafetyError):
                extraction_target(root, "../escape.pth")


if __name__ == "__main__":
    unittest.main()
