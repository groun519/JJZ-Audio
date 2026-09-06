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


class CompleteRemovalUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    def test_normal_removal_and_work_preservation_are_the_defaults(self) -> None:
        dialog = _section(
            self.installer,
            "function ShowRemovalOptionsDialog: Boolean;",
            "function InitializeUninstall: Boolean;",
        )

        self.assertIn("NormalRemovalRadio.Checked := True", dialog)
        self.assertIn("DeleteUserWorkCheckBox.Checked := False", dialog)
        self.assertIn("SetCompleteRemovalOptions(False, False)", self.installer)

    def test_work_deletion_requires_complete_mode_and_safe_layout(self) -> None:
        state = _section(
            self.installer,
            "procedure UpdateRemovalOptionsState;",
            "procedure RemovalModeOnClick",
        )

        self.assertIn("CompleteRemovalRadio.Checked and RemovalOptionsLayoutReady", state)
        self.assertIn("DeleteUserWorkCheckBox.Checked := False", state)

    def test_dialog_displays_verified_data_and_output_paths(self) -> None:
        dialog = _section(
            self.installer,
            "function ShowRemovalOptionsDialog: Boolean;",
            "function InitializeUninstall: Boolean;",
        )

        self.assertIn("TryLoadSafeStorageLayout(", dialog)
        self.assertIn("'Data: ' + RemovalOptionsWorkspaceRoot", dialog)
        self.assertIn("'Output: ' + RemovalOptionsOutputRoot", dialog)
        self.assertIn("RemovalOptionsFailureReason", dialog)

    def test_work_deletion_has_a_second_confirmation(self) -> None:
        confirm = _section(
            self.installer,
            "function ConfirmRemovalWorkDeletion: Boolean;",
            "function ShowRemovalOptionsDialog: Boolean;",
        )

        self.assertIn("DeleteUserWorkCheckBox.Checked", confirm)
        self.assertIn("MB_YESNO or MB_DEFBUTTON2", confirm)
        self.assertIn("= idYes", confirm)

    def test_interactive_choice_is_applied_only_after_dialog_acceptance(self) -> None:
        dialog = _section(
            self.installer,
            "function ShowRemovalOptionsDialog: Boolean;",
            "function InitializeUninstall: Boolean;",
        )

        self.assertIn("DialogAccepted := RemovalOptionsForm.ShowModal = mrOk", dialog)
        self.assertIn("Result := ConfirmRemovalWorkDeletion", dialog)
        self.assertIn("if Result then", dialog)
        self.assertIn(
            "SetCompleteRemovalOptions(\n        CompleteRemovalRadio.Checked,",
            dialog,
        )

    def test_silent_public_uninstall_keeps_normal_mode(self) -> None:
        initialize = _section(
            self.installer,
            "function InitializeUninstall: Boolean;",
            "procedure CurUninstallStepChanged",
        )

        self.assertIn("not UninstallSilent", initialize)
        self.assertIn("not CompleteRemovalRequested", initialize)
        self.assertIn("ShowRemovalOptionsDialog", initialize)


if __name__ == "__main__":
    unittest.main()
