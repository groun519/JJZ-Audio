from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from jang_app.services.app_update import ReleaseArtifact, ReleaseComponent, ReleaseManifest
from scripts.verify_component_release import (
    _accelerator_metadata_matches,
    _verify_cu128_package_layout,
)


class ComponentReleaseValidationTests(unittest.TestCase):
    def test_accepts_only_the_pinned_amd_runtime_metadata(self) -> None:
        self.assertTrue(
            _accelerator_metadata_matches(
                "directml",
                {
                    "torch": "2.4.1 / torch-directml 0.2.5.dev240914",
                    "python": "3.9",
                    "hardware_validation": "validated_at_build",
                    "operation_validation": "inference_forward",
                },
            )
        )
        self.assertTrue(
            _accelerator_metadata_matches(
                "rocm-win",
                {
                    "torch": "2.9.1 / ROCm 7.2.1",
                    "python": "3.12",
                    "hardware_validation": "required_on_install",
                    "operation_validation": "required_on_install",
                },
            )
        )
        self.assertFalse(
            _accelerator_metadata_matches(
                "rocm-win",
                {
                    "torch": "2.9 / CUDA 12.8",
                    "python": "3.12",
                    "hardware_validation": "required_on_install",
                    "operation_validation": "required_on_install",
                },
            )
        )

    def test_accepts_complete_cu128_profile_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "cu128.zip"
            _write_profile_package(package)

            _verify_cu128_package_layout(_manifest(package), root)

    def test_rejects_cu128_profile_without_torchaudio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "cu128.zip"
            _write_profile_package(
                package,
                omitted="Lib/site-packages/torchaudio/__init__.py",
            )

            with self.assertRaisesRegex(RuntimeError, "torchaudio"):
                _verify_cu128_package_layout(_manifest(package), root)


def _write_profile_package(path: Path, *, omitted: str = "") -> None:
    entries = {
        "python.exe": b"python",
        "python3.dll": b"dll",
        "Lib/site-packages/torch/__init__.py": b"torch",
        "Lib/site-packages/torchaudio/__init__.py": b"torchaudio",
        "Lib/site-packages/numpy/__init__.py": b"numpy",
        "Lib/site-packages/faiss/__init__.py": b"faiss",
        "Lib/site-packages/fairseq/__init__.py": b"fairseq",
        "jjzero-profile-build.json": json.dumps(
            {
                "schema_version": 1,
                "profile": "cu128",
                "torch": "2.7.1+cu128",
            }
        ).encode("utf-8"),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            if name != omitted:
                archive.writestr(name, data)


def _manifest(package: Path) -> ReleaseManifest:
    artifact = ReleaseArtifact(package.name, package.stat().st_size, "0" * 64, "https://example.invalid")
    application = ReleaseComponent("application", "0.2.2", "installer", ())
    profile = ReleaseComponent("rvc-runtime-cu128", "1", "extract", (artifact,))
    return ReleaseManifest("0.2.2", (application, profile))


if __name__ == "__main__":
    unittest.main()
