from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from jang_app.services.runtime_installation import (
    RuntimeInstallationError,
    install_rvc_runtime_profile_packages,
    install_runtime_packages,
    installed_rvc_runtime_profile,
    installed_runtime_version,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class RuntimeInstallationTests(unittest.TestCase):
    def test_installs_packages_atomically_and_preserves_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            (runtime / "rvc" / "weights").mkdir(parents=True)
            (runtime / "rvc" / "weights" / "voice.pth").write_bytes(b"voice")
            package = root / "runtime.zip"
            _write_runtime_package(package)

            progress: list[int] = []
            result = install_runtime_packages(
                (package,),
                runtime,
                "9",
                progress=progress.append,
            )

            self.assertEqual(result.version, "9")
            self.assertEqual(installed_runtime_version(runtime), "9")
            self.assertEqual((runtime / "rvc" / "weights" / "voice.pth").read_bytes(), b"voice")
            self.assertEqual(progress[-1], 100)
            state = json.loads((runtime / "runtime-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["version"], "9")
            profile = installed_rvc_runtime_profile(runtime / "rvc")
            self.assertEqual(profile.profile if profile else "", "cu118")
            self.assertEqual(profile.version if profile else "", "9")

    def test_installs_rvc_profile_atomically_without_touching_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc = root / "rvc"
            runtime = rvc / "runtime"
            (runtime / "Lib" / "site-packages" / "torch").mkdir(parents=True)
            (runtime / "python.exe").write_bytes(b"old")
            (rvc / "weights").mkdir()
            (rvc / "weights" / "voice.pth").write_bytes(b"model")
            profile_package = root / "cu128.zip"
            _write_profile_package(profile_package, b"new")

            result = install_rvc_runtime_profile_packages(
                (profile_package,),
                rvc,
                "cu128",
                "3",
                activation_validator=None,
            )

            self.assertEqual((runtime / "python.exe").read_bytes(), b"new")
            self.assertEqual((rvc / "weights" / "voice.pth").read_bytes(), b"model")
            self.assertEqual(result.profile, "cu128")
            self.assertEqual(installed_rvc_runtime_profile(rvc).version, "3")

    def test_failed_profile_activation_preserves_the_current_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc = root / "rvc"
            runtime = rvc / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "python.exe").write_bytes(b"current")
            profile_package = root / "rocm.zip"
            _write_profile_package(profile_package, b"candidate")

            with self.assertRaisesRegex(RuntimeError, "HIP probe failed"):
                install_rvc_runtime_profile_packages(
                    (profile_package,),
                    rvc,
                    "rocm-win",
                    "1",
                    activation_validator=lambda _profile, _root: (_ for _ in ()).throw(
                        RuntimeError("HIP probe failed")
                    ),
                )

            self.assertEqual((runtime / "python.exe").read_bytes(), b"current")

    def test_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "unsafe.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../outside.txt", b"bad")

            with self.assertRaises(RuntimeInstallationError):
                install_runtime_packages((package,), root / "runtime", "1")
            self.assertFalse((root / "outside.txt").exists())


def _write_runtime_package(path: Path) -> None:
    files = {
        "ffmpeg/bin/ffmpeg.exe": b"ffmpeg",
        "ffmpeg/bin/ffprobe.exe": b"ffprobe",
        "demucs/torch/hub/checkpoints/955717e8-8726e21a.th": b"model",
        "rvc/infer_cli.py": b"code",
        "rvc/runtime/python.exe": b"python",
        "rvc/hubert_base.pt": b"hubert",
        "rvc/rmvpe.pt": b"rmvpe",
    }
    files.update(
        {f"rvc/{required.as_posix()}": b"training" for required in required_rvc_training_paths()}
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def _write_profile_package(path: Path, python: bytes) -> None:
    files = {
        "python.exe": python,
        "python3.dll": b"dll",
        "Lib/site-packages/torch/__init__.py": b"torch",
        "Lib/site-packages/torchaudio/__init__.py": b"torchaudio",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


if __name__ == "__main__":
    unittest.main()
