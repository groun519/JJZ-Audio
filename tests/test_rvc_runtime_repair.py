from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_runtime_repair import (
    bundled_device_adapter,
    repair_rvc_runtime_adapter,
)


class RvcRuntimeRepairTests(unittest.TestCase):
    def test_missing_runtime_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "rvc"

            result = repair_rvc_runtime_adapter(root)

            self.assertEqual(result.status, "unavailable")
            self.assertFalse(result.target.exists())

    def test_missing_and_stale_adapters_are_repaired_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "rvc"
            root.mkdir()
            source = Path(temporary) / "adapter.py"
            source.write_text("ADAPTER_VERSION = 2\n", encoding="utf-8")

            first = repair_rvc_runtime_adapter(root, source)
            target = root / "lib" / "jjzero_device.py"
            self.assertEqual(first.status, "repaired")
            self.assertEqual(target.read_text(encoding="utf-8"), "ADAPTER_VERSION = 2\n")

            target.write_text("stale\n", encoding="utf-8")
            second = repair_rvc_runtime_adapter(root, source)
            third = repair_rvc_runtime_adapter(root, source)

            self.assertEqual(second.status, "repaired")
            self.assertEqual(third.status, "ready")
            self.assertEqual(target.read_text(encoding="utf-8"), "ADAPTER_VERSION = 2\n")

    def test_missing_bundled_source_reports_failure_without_mutating_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "rvc"
            root.mkdir()

            result = repair_rvc_runtime_adapter(root, Path(temporary) / "missing.py")

            self.assertEqual(result.status, "failed")
            self.assertFalse(result.target.exists())
            self.assertIn("missing", result.detail.lower())

if __name__ == "__main__":
    unittest.main()
