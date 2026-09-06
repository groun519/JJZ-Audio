from __future__ import annotations

import unittest
from pathlib import Path


INSTALLER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "packaging" / "JJZeroAudio.iss"
)
VERIFICATION_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "verify_complete_uninstall.ps1"
)


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


class CompleteRemovalEngineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")
        cls.verifier = VERIFICATION_SCRIPT.read_text(encoding="utf-8-sig")

    def test_automation_switches_exist_only_in_verification_builds(self) -> None:
        options = _section(
            self.installer,
            "procedure InitializeCompleteRemovalOptions;",
            "function CompleteRemovalCredentialTarget: String;",
        )

        self.assertIn("#ifdef VerificationBuild", options)
        self.assertIn("HasCommandLineSwitch('/JJZEROCOMPLETEREMOVAL')", options)
        self.assertIn("HasCommandLineSwitch('/JJZERODELETEWORK')", options)
        self.assertIn("SetCompleteRemovalOptions(False, False);", options)

    def test_complete_removal_deletes_runtime_cache_and_optional_work(self) -> None:
        engine = _section(
            self.installer,
            "procedure PrepareCompleteRemoval;",
            "procedure RemoveRuntimeRoot",
        )

        self.assertIn("TryLoadSafeStorageLayout(", engine)
        self.assertIn("'application-owned Runtime'", engine)
        self.assertIn("'configured Runtime'", engine)
        self.assertIn("'configured Cache'", engine)
        self.assertIn("if DeleteUserWorkRequested then", engine)
        self.assertIn("DeleteVerifiedTree(WorkspaceRoot, WorkspaceRoot, 'Data')", engine)
        self.assertIn("DeleteVerifiedTree(OutputRoot, OutputRoot, 'Output')", engine)
        self.assertIn("DeleteGoogleCredential;", engine)
        self.assertIn("DeleteLocalApplicationState(", engine)

    def test_complete_removal_does_not_preserve_runtime_assets(self) -> None:
        engine = _section(
            self.installer,
            "procedure PrepareCompleteRemoval;",
            "procedure RemoveRuntimeRoot",
        )

        self.assertNotIn("PreserveDirectory", engine)
        self.assertNotIn("UniquePreservationRoot", engine)

    def test_credential_deletion_targets_only_the_jjzero_entry(self) -> None:
        credential = _section(
            self.installer,
            "function DeleteGoogleCredential: Boolean;",
            "procedure PrepareCompleteRemoval;",
        )

        self.assertIn("CredDeleteW(TargetName, CredentialTypeGeneric, 0)", credential)
        self.assertIn("ErrorCode = ErrorNotFound", credential)
        self.assertIn("GoogleCredentialTarget = 'JJZero Audio/Google Drive'", self.installer)
        self.assertNotIn("CredEnumerate", self.installer)

    def test_local_state_preserves_nested_work_when_not_requested(self) -> None:
        local_state = _section(
            self.installer,
            "procedure DeleteLocalApplicationState",
            "function DeleteGoogleCredential",
        )

        self.assertIn("not DeleteUserWork", local_state)
        self.assertIn("PathContains(DataRoot, WorkspaceRoot)", local_state)
        self.assertIn("PathContains(DataRoot, OutputRoot)", local_state)
        self.assertIn("DeleteKnownLocalState;", local_state)

    def test_partial_failure_is_recorded_without_disabling_app_uninstall(self) -> None:
        engine = _section(
            self.installer,
            "procedure AppendCompleteRemovalFailure",
            "procedure RemoveRuntimeRoot",
        )
        uninstall = _section(
            self.installer,
            "procedure CurUninstallStepChanged",
            "end;\n",
        )

        self.assertIn("CompleteRemovalSucceeded := False", engine)
        self.assertIn("CompleteRemovalFailureDetails", engine)
        self.assertIn("if CompleteRemovalRequested then", uninstall)
        self.assertIn("PrepareCompleteRemoval", uninstall)
        self.assertIn("else\n      PrepareRuntimeRemoval", uninstall)

    def test_registry_restore_uses_process_exit_code_instead_of_stderr(self) -> None:
        self.assertIn("$registryImport = Start-Process", self.verifier)
        self.assertIn("$registryImport.ExitCode -ne 0", self.verifier)
        self.assertNotIn("& reg.exe import", self.verifier)


if __name__ == "__main__":
    unittest.main()
