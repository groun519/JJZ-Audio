from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.managed_files import write_json_atomic


class ManagedFilesTests(unittest.TestCase):
    def test_json_write_retries_a_transient_windows_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            with patch(
                "jang_app.services.managed_files.os.replace",
                side_effect=(PermissionError("locked"), None),
            ) as replace:
                write_json_atomic(target, {"ready": True})

            self.assertEqual(replace.call_count, 2)
            self.assertFalse(target.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
