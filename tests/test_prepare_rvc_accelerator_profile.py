from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_rvc_accelerator_profile import (
    _patch_directml_staticmethod_defaults,
    is_compatible_rocm_hip_version,
    prepare_directml_profile,
    prepare_rocm_windows_profile,
)


class PrepareRvcAcceleratorProfileTests(unittest.TestCase):
    def test_accepts_rocm_internal_hip_build_version_for_release_series(self) -> None:
        self.assertTrue(is_compatible_rocm_hip_version("7.2.53211-158bd99533"))
        self.assertTrue(is_compatible_rocm_hip_version("7.2.1"))
        self.assertFalse(is_compatible_rocm_hip_version("7.1.9"))
        self.assertFalse(is_compatible_rocm_hip_version("7.3.0"))
        self.assertFalse(is_compatible_rocm_hip_version(""))

    def test_patches_directml_python_39_staticmethod_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "Lib" / "site-packages" / "torch_directml"
            package.mkdir(parents=True)
            target = package / "__init__.py"
            target.write_text(
                "def has_float64_support(device_id = default_device()): pass\n"
                "def gpu_memory(device_id = default_device()): pass\n",
                encoding="utf-8",
            )

            _patch_directml_staticmethod_defaults(root)

            content = target.read_text(encoding="utf-8")
            self.assertEqual(content.count("torch_directml_native.get_default_device()"), 2)

    def test_prepares_directml_copy_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _runtime(root / "source")
            destination = root / "profiles" / "directml"

            result = prepare_directml_profile(source, destination, install_packages=False)

            self.assertEqual(result, destination.resolve())
            self.assertEqual((source / "source.txt").read_text(encoding="utf-8"), "original")
            metadata = json.loads(
                (destination / "jjzero-profile-build.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["profile"], "directml")
            self.assertEqual(metadata["hardware_validation"], "not_run")
            self.assertEqual(metadata["operation_validation"], "not_run")

    def test_prepares_prevalidated_rocm_runtime_as_a_separate_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _runtime(root / "rocm-source")
            destination = root / "profiles" / "rocm-win"

            result = prepare_rocm_windows_profile(
                source,
                destination,
                validate_gpu=False,
            )

            self.assertEqual(result, destination.resolve())
            metadata = json.loads(
                (destination / "jjzero-profile-build.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["profile"], "rocm-win")
            self.assertEqual(metadata["python"], "3.12")
            self.assertEqual(metadata["hardware_validation"], "required_on_install")
            self.assertEqual(metadata["operation_validation"], "required_on_install")


def _runtime(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "python.exe").write_bytes(b"python")
    (path / "source.txt").write_text("original", encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
