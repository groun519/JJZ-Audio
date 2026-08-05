from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_rvc_runtime_profile import prepare_cu128_profile


class PrepareRvcRuntimeProfileTests(unittest.TestCase):
    def test_copies_profile_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "profiles" / "cu128"
            source.mkdir()
            (source / "python.exe").write_bytes(b"python")
            (source / "source.txt").write_text("original", encoding="utf-8")

            result = prepare_cu128_profile(
                source,
                destination,
                install_packages=False,
            )

            self.assertEqual(result, destination.resolve())
            self.assertEqual((source / "source.txt").read_text(encoding="utf-8"), "original")
            manifest = json.loads(
                (destination / "jjzero-profile-build.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["profile"], "cu128")

    def test_rejects_destination_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "python.exe").write_bytes(b"python")

            with self.assertRaises(ValueError):
                prepare_cu128_profile(
                    source,
                    source / "cu128",
                    install_packages=False,
                )


if __name__ == "__main__":
    unittest.main()
