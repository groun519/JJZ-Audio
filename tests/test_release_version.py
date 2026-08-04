from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.release_version import load_release_version, write_windows_version_info


class ReleaseVersionTests(unittest.TestCase):
    def test_loads_semantic_version_from_python_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / "version.py"
            module.write_text('__version__ = "1.2.3"\n', encoding="utf-8")

            self.assertEqual(load_release_version(module), "1.2.3")

    def test_rejects_non_release_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / "version.py"
            module.write_text('__version__ = "1.2-beta"\n', encoding="utf-8")

            with self.assertRaises(ValueError):
                load_release_version(module)

    def test_generates_windows_metadata_from_release_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "windows_version_info.txt"

            write_windows_version_info(destination, "2.4.6")

            text = destination.read_text(encoding="utf-8")
            self.assertIn("filevers=(2, 4, 6, 0)", text)
            self.assertIn("ProductVersion', u'2.4.6'", text)


if __name__ == "__main__":
    unittest.main()
