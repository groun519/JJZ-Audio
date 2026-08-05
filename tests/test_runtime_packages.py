from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_runtime_packages import build_component_packages, build_runtime_packages


class RuntimePackagesTests(unittest.TestCase):
    def test_builds_bounded_deterministic_runtime_parts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            release = root / "release"
            (runtime / "rvc").mkdir(parents=True)
            (runtime / "rvc" / "a.bin").write_bytes(b"a" * 7)
            (runtime / "rvc" / "b.bin").write_bytes(b"b" * 6)
            (runtime / "ffmpeg.exe").write_bytes(b"f" * 5)

            index = build_runtime_packages(runtime, release, "3", part_limit=11)

            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "3")
            self.assertEqual(len(data["artifacts"]), 2)
            archived: set[str] = set()
            for artifact in data["artifacts"]:
                self.assertLessEqual(artifact["unpacked_size"], 11)
                with zipfile.ZipFile(release / artifact["name"]) as package:
                    archived.update(package.namelist())
            self.assertEqual(
                archived,
                {"ffmpeg.exe", "rvc/a.bin", "rvc/b.bin"},
            )

    def test_builds_named_rvc_profile_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "cu128"
            release = root / "release"
            profile.mkdir()
            (profile / "python.exe").write_bytes(b"python")

            index = build_component_packages(
                profile,
                release,
                "2",
                component="rvc-runtime-cu128",
                package_prefix="JJZero-RVC-cu128-2",
                index_name="rvc-runtime-cu128-packages.json",
                part_limit=100,
            )

            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(data["component"], "rvc-runtime-cu128")
            self.assertEqual(data["artifacts"][0]["name"], "JJZero-RVC-cu128-2-part01.zip")


if __name__ == "__main__":
    unittest.main()
