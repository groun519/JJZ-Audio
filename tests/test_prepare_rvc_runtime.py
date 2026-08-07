from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_rvc_runtime import (
    DIRECTML_PROFILE_ASSET_FILES,
    MANIFEST_FILE,
    RUNTIME_DIRECTORIES,
    RUNTIME_FILES,
    TRAINING_ASSET_FILES,
    prepare_rvc_runtime,
)


class PrepareRvcRuntimeTests(unittest.TestCase):
    def test_copies_runtime_without_model_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            self._create_source(source)
            (source / "weights").mkdir()
            (source / "weights" / "private-model.pth").write_bytes(b"private")
            cache = source / "runtime" / "__pycache__"
            cache.mkdir()
            (cache / "module.cpython-39.pyc").write_bytes(b"cache")

            result = prepare_rvc_runtime(source, destination, install_demucs=False)

            self.assertEqual(result, destination)
            self.assertTrue((destination / "runtime" / "python.exe").is_file())
            self.assertTrue((destination / "infer_cli.py").is_file())
            self.assertTrue((destination / MANIFEST_FILE).is_file())
            self.assertFalse((destination / "weights" / "private-model.pth").exists())
            self.assertFalse((destination / "runtime" / "__pycache__").exists())
            self.assertTrue((destination / "weights").is_dir())
            self.assertTrue((destination / "logs").is_dir())
            self.assertFalse((destination / "rmvpe.onnx").exists())
            self.assertTrue(
                (destination.parent / "rvc_profiles" / "assets" / "rmvpe.onnx").is_file()
            )
            self.assertTrue((destination / "pretrained_v2" / "f0G40k.pth").is_file())
            self.assertTrue((destination / "logs" / "mute" / "3_feature768" / "mute.npy").is_file())
            manifest = json.loads((destination / MANIFEST_FILE).read_text(encoding="utf-8"))
            self.assertEqual(manifest["layout_version"], 2)
            self.assertEqual(manifest["training_profile"]["sample_rate"], 40000)

    def test_rejects_destination_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            self._create_source(source)

            with self.assertRaises(ValueError):
                prepare_rvc_runtime(
                    source,
                    source / "runtime-copy",
                    install_demucs=False,
                )

    @staticmethod
    def _create_source(source: Path) -> None:
        source.mkdir()
        for directory_name in RUNTIME_DIRECTORIES:
            directory = source / directory_name
            directory.mkdir()
            (directory / "content.bin").write_bytes(b"content")
        (source / "runtime" / "python.exe").write_bytes(b"python")
        for file_name in RUNTIME_FILES:
            (source / file_name).write_bytes(b"content")
        for file_name in DIRECTML_PROFILE_ASSET_FILES:
            (source / file_name).write_bytes(b"directml")
        for relative_path in TRAINING_ASSET_FILES:
            path = source / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"training")


if __name__ == "__main__":
    unittest.main()
