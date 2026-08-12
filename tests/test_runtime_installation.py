from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
import os
from pathlib import Path
from unittest.mock import patch

from jang_app.services.runtime_installation import (
    RuntimeInstallationError,
    install_rvc_runtime_profile_packages,
    install_runtime_packages,
    installed_rvc_runtime_profile,
    installed_runtime_version,
)
from jang_app.services.rvc_runtime_repair import bundled_device_adapter
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class RuntimeInstallationTests(unittest.TestCase):
    def test_installs_packages_atomically_and_preserves_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            (runtime / "rvc" / "weights").mkdir(parents=True)
            (runtime / "rvc" / "weights" / "voice.pth").write_bytes(b"voice")
            checkpoint_root = runtime / "demucs" / "torch" / "hub" / "checkpoints"
            checkpoint_root.mkdir(parents=True)
            (checkpoint_root / "f7e0c4bc-ba3fe64a.th").write_bytes(b"fine-tuned")
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
            self.assertEqual(
                (checkpoint_root / "f7e0c4bc-ba3fe64a.th").read_bytes(),
                b"fine-tuned",
            )
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

    def test_retries_rvc_profile_swap_when_windows_temporarily_locks_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rvc = root / "rvc"
            runtime = rvc / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "python.exe").write_bytes(b"old")
            profile_package = root / "cu128.zip"
            _write_profile_package(profile_package, b"new")
            real_replace = os.replace
            blocked_once = False

            def replace_with_transient_lock(source: Path, destination: Path) -> None:
                nonlocal blocked_once
                if Path(source).name == ".runtime.installing" and not blocked_once:
                    blocked_once = True
                    raise PermissionError(5, "The destination is temporarily locked")
                real_replace(source, destination)

            with patch(
                "jang_app.services.runtime_installation.os.replace",
                side_effect=replace_with_transient_lock,
            ):
                install_rvc_runtime_profile_packages(
                    (profile_package,),
                    rvc,
                    "cu128",
                    "3",
                    activation_validator=None,
                )

            self.assertTrue(blocked_once)
            self.assertEqual((runtime / "python.exe").read_bytes(), b"new")

    def test_repairs_adapter_omitted_from_base_runtime_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            package = root / "runtime.zip"
            _write_runtime_package(package, include_adapter=False)

            install_runtime_packages((package,), runtime, "9")

            adapter = runtime / "rvc" / "lib" / "jjzero_device.py"
            self.assertEqual(adapter.read_bytes(), bundled_device_adapter().read_bytes())
            self.assertEqual(installed_runtime_version(runtime), "9")

    def test_rejects_runtime_without_precision_separation_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            package = root / "runtime.zip"
            _write_runtime_package(package, include_precision_separation=False)

            with self.assertRaisesRegex(
                RuntimeInstallationError,
                "audio engine is incomplete",
            ):
                install_runtime_packages((package,), runtime, "9")

    def test_split_shared_runtime_preserves_the_installed_rvc_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            legacy_package = root / "legacy.zip"
            shared_package = root / "shared.zip"
            _write_runtime_package(legacy_package)
            _write_runtime_package(shared_package, include_runtime=False)

            install_runtime_packages((legacy_package,), runtime, "2")
            previous = installed_rvc_runtime_profile(runtime / "rvc")
            previous_python = (runtime / "rvc" / "runtime" / "python.exe").read_bytes()
            cache = runtime / "rvc" / "runtime" / "module" / "__pycache__" / "cache.pyc"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"cache")
            source_map = runtime / "rvc" / "runtime" / "web.js.map"
            source_map.write_bytes(b"source-map")
            install_runtime_packages((shared_package,), runtime, "3")
            preserved = installed_rvc_runtime_profile(runtime / "rvc")

            self.assertEqual(installed_runtime_version(runtime), "3")
            self.assertEqual(preserved, previous)
            self.assertEqual(
                (runtime / "rvc" / "runtime" / "python.exe").read_bytes(),
                previous_python,
            )
            self.assertFalse(cache.exists())
            self.assertFalse(source_map.exists())

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


def _write_runtime_package(
    path: Path,
    *,
    include_adapter: bool = True,
    include_runtime: bool = True,
    include_precision_separation: bool = True,
) -> None:
    files = {
        "ffmpeg/bin/ffmpeg.exe": b"ffmpeg",
        "ffmpeg/bin/ffprobe.exe": b"ffprobe",
        "demucs/torch/hub/checkpoints/955717e8-8726e21a.th": b"model",
        "rvc/infer_cli.py": b"code",
        "rvc/hubert_base.pt": b"hubert",
        "rvc/rmvpe.pt": b"rmvpe",
    }
    if include_runtime:
        files.update(
            {
                "rvc/runtime/python.exe": b"python",
                "rvc/runtime/python3.dll": b"dll",
                "rvc/runtime/Lib/site-packages/torch/__init__.py": b"torch",
                "rvc/runtime/Lib/site-packages/torchaudio/__init__.py": b"torchaudio",
            }
        )
        if include_precision_separation:
            files[
                "rvc/runtime/jjzero-roformer-packages/audio_separator/__init__.py"
            ] = b"package"
    training_paths = required_rvc_training_paths()
    if not include_runtime:
        training_paths = tuple(
            required for required in training_paths if required.parts[0] != "runtime"
        )
    if not include_adapter:
        training_paths = tuple(
            required for required in training_paths if required != Path("lib/jjzero_device.py")
        )
    files.update({f"rvc/{required.as_posix()}": b"training" for required in training_paths})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def _write_profile_package(path: Path, python: bytes) -> None:
    files = {
        "python.exe": python,
        "python3.dll": b"dll",
        "Lib/site-packages/torch/__init__.py": b"torch",
        "Lib/site-packages/torchaudio/__init__.py": b"torchaudio",
        "jjzero-roformer-packages/audio_separator/__init__.py": b"separator",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


if __name__ == "__main__":
    unittest.main()
