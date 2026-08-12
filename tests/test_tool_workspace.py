from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.tool_workspace import (
    ToolWorkspace,
    new_storage_key,
    stable_storage_key,
)


class ToolWorkspaceTests(unittest.TestCase):
    def test_storage_keys_are_short_and_display_name_independent(self) -> None:
        identity = "very long display title / invalid:*? name"

        self.assertEqual(
            stable_storage_key("s", identity),
            stable_storage_key("s", identity),
        )
        self.assertRegex(stable_storage_key("s", identity), r"^s_[0-9a-f]{16}$")
        self.assertRegex(new_storage_key("r"), r"^r_[0-9a-f]{12}$")

    def test_workspace_stages_and_publishes_files_then_cleans_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "very long display name.wav"
            source.write_bytes(b"audio")
            target = root / "result" / "vocals.wav"

            with ToolWorkspace(root / "cache", "demucs") as workspace:
                staged = workspace.stage_input(source)
                workspace.publish_file(staged, target)
                transient_root = workspace.root
                self.assertEqual(staged.name, "i.wav")
                self.assertTrue(staged.is_file())
                self.assertEqual(target.read_bytes(), b"audio")

            self.assertFalse(transient_root.exists())
            self.assertEqual(target.read_bytes(), b"audio")


if __name__ == "__main__":
    unittest.main()
