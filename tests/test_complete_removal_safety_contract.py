from __future__ import annotations

import unittest
from pathlib import Path


INSTALLER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "packaging" / "JJZeroAudio.iss"
)


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


class CompleteRemovalSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    def test_storage_settings_are_read_strictly_as_utf8(self) -> None:
        loader = _section(
            self.installer,
            "function TryLoadStorageSettings",
            "function StorageMarkerOccursOnce",
        )
        path_reader = _section(
            self.installer,
            "function TryReadStoragePath",
            "function TryReadStorageVersion",
        )
        version_reader = _section(
            self.installer,
            "function TryReadStorageVersion",
            "function ReadStoragePath",
        )

        self.assertIn("Utf8Decode(RawContent)", loader)
        self.assertIn("TrimmedContent[1] <> '{'", loader)
        self.assertIn("TrimmedContent[Length(TrimmedContent)] <> '}'", loader)
        self.assertIn("StorageMarkerOccursOnce(Content, Marker)", path_reader)
        self.assertIn("StorageMarkerOccursOnce(Content, Marker)", version_reader)
        self.assertIn("(Version <> 2) and (Version <> 3)", version_reader)

    def test_deletion_candidate_must_match_a_saved_existing_path(self) -> None:
        canonical = _section(
            self.installer,
            "function IsCanonicalAbsolutePath",
            "function IsDriveOrShareRoot",
        )
        validator = _section(
            self.installer,
            "function ValidateConfiguredDeletionRoot",
            "function TryLoadSafeStorageLayout",
        )

        self.assertIn("PathHasInvalidCharacters(RawPath, True)", canonical)
        self.assertIn("Copy(RawPath, 1, 4) = '\\\\?\\'", canonical)
        self.assertIn("Copy(RawPath, 1, 4) = '\\\\.\\'", canonical)
        self.assertIn("Pos('~', RawPath) > 0", canonical)
        self.assertIn("IsCanonicalAbsolutePath(Candidate)", validator)
        self.assertIn("SamePath(Candidate, ExpectedRoot)", validator)
        self.assertIn("IsDangerousDeletionRoot(Candidate)", validator)
        self.assertIn("DirExists(NormalizedCandidate)", validator)
        self.assertIn("FailureReason :=", validator)

    def test_protected_windows_and_user_roots_are_rejected(self) -> None:
        protected = _section(
            self.installer,
            "function IsInsideSystemTree",
            "function ValidateConfiguredDeletionRoot",
        )
        for value in (
            "IsDriveOrShareRoot(Candidate)",
            "ExpandConstant('{win}')",
            "ExpandConstant('{commonpf}')",
            "ExpandConstant('{commonpf32}')",
            "ExpandConstant('{commonpf64}')",
            "GetEnv('USERPROFILE')",
            "ExpandConstant('{userdocs}')",
            "ExpandConstant('{userdesktop}')",
            "'Downloads'",
            "ExpandConstant('{localappdata}')",
            "ExpandConstant('{userappdata}')",
            "ExpandConstant('{userpf}')",
            "ExpandConstant('{app}')",
            "RuntimeDataRoot",
        ):
            self.assertIn(value, protected)

    def test_reparse_points_cannot_redirect_a_deletion(self) -> None:
        parent_guard = _section(
            self.installer,
            "function PathHasReparsePoint",
            "function TreeHasReparsePoint",
        )
        tree_guard = _section(
            self.installer,
            "function TreeHasReparsePoint",
            "function CandidateThreatensRoot",
        )
        validator = _section(
            self.installer,
            "function ValidateConfiguredDeletionRoot",
            "function TryLoadSafeStorageLayout",
        )

        self.assertIn("GetFileAttributesW(CurrentPath)", parent_guard)
        self.assertIn("FileAttributeReparsePoint", parent_guard)
        self.assertIn("ExtractFileDir(CurrentPath)", parent_guard)
        self.assertIn("Entry.Attributes and FileAttributeReparsePoint", tree_guard)
        self.assertIn("TreeHasReparsePoint(ChildPath)", tree_guard)
        self.assertIn("PathHasReparsePoint(Candidate)", validator)
        self.assertIn("TreeHasReparsePoint(Candidate)", validator)

    def test_storage_layout_rejects_missing_and_overlapping_roots(self) -> None:
        layout = _section(
            self.installer,
            "function TryLoadSafeStorageLayout",
            "function IsSafeGeneratedRoot",
        )

        for key in (
            "storage_root",
            "workspace_root",
            "output_root",
            "runtime_root",
            "cache_root",
        ):
            self.assertIn(f"TryReadStoragePath(Content, '{key}'", layout)
        self.assertIn("DirExists(NormalizePath(StorageRoot))", layout)
        self.assertEqual(layout.count("ValidateConfiguredDeletionRoot("), 4)
        self.assertEqual(layout.count("PathsOverlap("), 6)
        self.assertIn("Saved storage folders overlap; removal was refused.", layout)

    def test_normal_uninstall_uses_the_same_protected_root_guard(self) -> None:
        normal_guard = _section(
            self.installer,
            "function IsSafeGeneratedRoot",
            "function DirectoryHasContents",
        )

        self.assertIn("IsDangerousDeletionRoot(Candidate)", normal_guard)


if __name__ == "__main__":
    unittest.main()
