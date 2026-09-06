from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SCRIPT = ROOT / "packaging" / "JJZeroAudio.iss"
VERIFICATION_SCRIPT = ROOT / "scripts" / "verify_uninstaller_storage.ps1"


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


class NormalUninstallContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")
        cls.verifier = VERIFICATION_SCRIPT.read_text(encoding="utf-8-sig")

    def test_only_application_owned_runtime_is_removed(self) -> None:
        removal = _section(
            self.installer,
            "procedure PrepareRuntimeRemoval;",
            "function InitializeUninstall: Boolean;",
        )

        self.assertIn("RemoveRuntimeRoot(AppRuntimeRoot);", removal)
        self.assertNotIn("RemoveRuntimeRoot(ConfiguredRuntimeRoot);", removal)
        self.assertIn("if not SamePath(AppRuntimeRoot, ConfiguredRuntimeRoot) then", removal)
        self.assertIn("PreservedExternalStorage := True;", removal)

    def test_only_default_managed_cache_is_removed(self) -> None:
        removal = _section(
            self.installer,
            "procedure PrepareRuntimeRemoval;",
            "function InitializeUninstall: Boolean;",
        )

        self.assertIn("DefaultCacheRoot := AddBackslash(RuntimeDataRoot) + 'cache';", removal)
        self.assertIn("if SamePath(ConfiguredCacheRoot, DefaultCacheRoot) then", removal)
        self.assertIn("DelTree(ConfiguredCacheRoot, True, True, True)", removal)
        self.assertIn("else\n    PreservedExternalStorage := True;", removal)

    def test_user_work_and_rvc_assets_are_protected(self) -> None:
        safety = _section(
            self.installer,
            "function IsSafeGeneratedRoot(const Candidate: String): Boolean;",
            "function DirectoryHasContents(const Directory: String): Boolean;",
        )
        runtime = _section(
            self.installer,
            "procedure RemoveRuntimeRoot(const RuntimeRoot: String);",
            "procedure PrepareRuntimeRemoval;",
        )

        self.assertIn("ReadStoragePath('workspace_root')", safety)
        self.assertIn("ReadStoragePath('output_root')", safety)
        self.assertIn("PathContains(Candidate, WorkspaceRoot)", safety)
        self.assertIn("PathContains(Candidate, OutputRoot)", safety)
        self.assertIn("PathContains(Candidate, RuntimeDataRoot)", safety)
        self.assertIn("AddBackslash(RvcRoot) + 'weights'", runtime)
        self.assertIn("AddBackslash(RvcRoot) + 'logs'", runtime)
        self.assertEqual(runtime.count("PreserveDirectory("), 2)

    def test_uninstall_is_blocked_while_the_app_mutex_exists(self) -> None:
        initialize = _section(
            self.installer,
            "function InitializeUninstall: Boolean;",
            "procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);",
        )

        self.assertIn("Result := not CheckForMutexes('{#AppMutexName}');", initialize)

    def test_live_verifier_covers_managed_and_external_storage(self) -> None:
        self.assertIn('[ValidateSet("All", "Managed", "External")]', self.verifier)
        self.assertIn('Assert-Removed -LiteralPath $appRuntimeRoot', self.verifier)
        self.assertIn('Assert-Removed -LiteralPath $defaultCacheRoot', self.verifier)
        self.assertIn('Assert-Exists -LiteralPath $runtimeSentinel', self.verifier)
        self.assertIn('Assert-Exists -LiteralPath $cacheSentinel', self.verifier)
        self.assertIn('Join-Path $dataRoot "preserved-runtime"', self.verifier)

    def test_registry_restore_uses_process_exit_code_instead_of_stderr(self) -> None:
        self.assertIn("$registryImport = Start-Process", self.verifier)
        self.assertIn("$registryImport.ExitCode -ne 0", self.verifier)
        self.assertNotIn("& reg.exe import", self.verifier)


if __name__ == "__main__":
    unittest.main()
