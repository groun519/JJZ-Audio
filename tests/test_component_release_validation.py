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
    _verify_split_runtime_package_layout,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class ComponentReleaseValidationTests(unittest.TestCase):
    def test_accepts_only_the_pinned_amd_runtime_metadata(self) -> None:
        self.assertTrue(
            _accelerator_metadata_matches(
                "directml",
                {
                    "torch": "2.4.1 / torch-directml 0.2.5.dev240914",
                    "python": "3.9",
                    "hardware_validation": "validated_at_build",
                    "operation_validation": "inference_forward_and_onnx_provider",
                    "onnxruntime": "1.19.2 / DirectML",
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

    def test_rejects_cu128_profile_without_precision_separator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "cu128.zip"
            _write_profile_package(
                package,
                omitted="jjzero-roformer-packages/audio_separator/__init__.py",
            )

            with self.assertRaisesRegex(RuntimeError, "audio_separator"):
                _verify_cu128_package_layout(_manifest(package), root)

    def test_accepts_runtime_with_separate_cu118_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _split_manifest(root)

            _verify_split_runtime_package_layout(manifest, root)

    def test_rejects_split_runtime_that_embeds_cu118_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _split_manifest(root, embedded_runtime=True)

            with self.assertRaisesRegex(RuntimeError, "RVC profile file"):
                _verify_split_runtime_package_layout(manifest, root)


def _write_profile_package(path: Path, *, omitted: str = "") -> None:
    entries = {
        "python.exe": b"python",
        "python3.dll": b"dll",
        "Lib/site-packages/torch/__init__.py": b"torch",
        "Lib/site-packages/torchaudio/__init__.py": b"torchaudio",
        "Lib/site-packages/numpy/__init__.py": b"numpy",
        "Lib/site-packages/faiss/__init__.py": b"faiss",
        "Lib/site-packages/fairseq/__init__.py": b"fairseq",
        "jjzero-roformer-packages/audio_separator/__init__.py": b"audio-separator",
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


def _split_manifest(root: Path, *, embedded_runtime: bool = False) -> ReleaseManifest:
    shared = root / "shared.zip"
    profile = root / "cu118.zip"
    shared_entries = {
        "ffmpeg/bin/ffmpeg.exe",
        "ffmpeg/bin/ffprobe.exe",
        "demucs/torch/hub/checkpoints/955717e8-8726e21a.th",
        "rvc/infer_cli.py",
        "rvc/hubert_base.pt",
        "rvc/rmvpe.pt",
        *(
            f"rvc/{path.as_posix()}"
            for path in required_rvc_training_paths()
            if path.parts[0] != "runtime"
        ),
    }
    if embedded_runtime:
        shared_entries.add("rvc/runtime/python.exe")
    with zipfile.ZipFile(shared, "w") as archive:
        for name in shared_entries:
            archive.writestr(name, b"shared")
    with zipfile.ZipFile(profile, "w") as archive:
        for name in (
            "python.exe",
            "python3.dll",
            "Lib/site-packages/torch/__init__.py",
            "Lib/site-packages/torchaudio/__init__.py",
            "jjzero-roformer-packages/audio_separator/__init__.py",
        ):
            archive.writestr(name, b"profile")
    artifact = lambda path: ReleaseArtifact(
        path.name,
        path.stat().st_size,
        "0" * 64,
        "https://example.invalid",
    )
    return ReleaseManifest(
        "0.3.0",
        (
            ReleaseComponent("application", "0.3.0", "installer", ()),
            ReleaseComponent("ai-runtime", "3", "extract", (artifact(shared),)),
            ReleaseComponent("rvc-runtime-cu118", "2", "extract", (artifact(profile),)),
        ),
    )


if __name__ == "__main__":
    unittest.main()
