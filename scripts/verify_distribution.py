from __future__ import annotations

import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from jang_app.services.rvc_training_runtime import required_rvc_training_paths


EXECUTABLE_NAME = "JJZero Audio.exe"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a JJZero Audio distribution.")
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--app-only", action="store_true")
    arguments = parser.parse_args()
    distribution = arguments.distribution.expanduser().resolve()
    executable = distribution / EXECUTABLE_NAME
    rvc_root = distribution / "runtime" / "rvc"
    rvc_python = rvc_root / "runtime" / "python.exe"
    required_files = required_application_files(distribution)
    if not arguments.app_only:
        required_files += required_runtime_files(distribution)
    missing = tuple(path for path in required_files if not path.is_file())
    if missing:
        for path in missing:
            print(f"Missing distribution file: {path}", file=sys.stderr)
        return 1

    if not arguments.app_only:
        demucs_check = subprocess.run(
            [str(rvc_python), "-m", "demucs", "--help"],
            cwd=distribution,
            check=False,
            timeout=90,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if demucs_check.returncode != 0:
            print(
                f"Packaged Demucs runtime failed with exit code {demucs_check.returncode}",
                file=sys.stderr,
            )
            return 1
        if not _verify_demucs_runtime(distribution, rvc_python):
            return 1
        if not _verify_rvc_runtime(distribution):
            return 1

    with tempfile.TemporaryDirectory(prefix="jjzero-dist-smoke-") as temporary:
        temporary_root = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            {
                "JJZERO_DATA_ROOT": str(temporary_root / "local-data"),
                "JJZERO_WORKSPACE_ROOT": str(temporary_root / "media" / "workspace"),
                "JJZERO_WORKSPACE_ANCHOR": str(temporary_root / "media"),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        completed = subprocess.run(
            [str(executable), "--startup-smoke-test"],
            cwd=distribution,
            env=environment,
            check=False,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            print(f"Packaged startup failed with exit code {completed.returncode}", file=sys.stderr)
            return 1

        log_file = temporary_root / "local-data" / "logs" / "jang.log"
        log_text = log_file.read_text(encoding="utf-8") if log_file.is_file() else ""
        if "Startup timing" not in log_text:
            print(f"Packaged startup timing was not logged: {log_file}", file=sys.stderr)
            return 1
        initialized_paths = (
            temporary_root / "local-data" / "settings" / "storage.json",
            temporary_root / "local-data" / "settings" / "initial_setup.json",
            temporary_root / "media" / "workspace",
            temporary_root / "media" / "output",
        )
        missing_setup = tuple(path for path in initialized_paths if not path.exists())
        if missing_setup:
            print(f"Packaged first-run setup was not completed: {missing_setup[0]}", file=sys.stderr)
            return 1

    print(f"Verified distribution: {distribution}")
    return 0


def required_application_files(distribution: Path) -> tuple[Path, ...]:
    root = distribution.expanduser().resolve()
    return (
        root / EXECUTABLE_NAME,
        root / "_internal" / "jang_app" / "assets" / "jjzero_logo.svg",
        root / "_internal" / "jang_app" / "rvc_tools" / "rvc_artifact_worker.py",
        root / "_internal" / "jang_app" / "rvc_tools" / "jjzero_device.py",
    )


def required_runtime_files(distribution: Path) -> tuple[Path, ...]:
    root = distribution.expanduser().resolve()
    rvc_root = root / "runtime" / "rvc"
    return (
        rvc_root / "runtime" / "python.exe",
        rvc_root
        / "runtime"
        / "jjzero-roformer-packages"
        / "audio_separator"
        / "__init__.py",
        root / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
        root / "runtime" / "ffmpeg" / "bin" / "ffprobe.exe",
        root
        / "runtime"
        / "demucs"
        / "torch"
        / "hub"
        / "checkpoints"
        / "955717e8-8726e21a.th",
        rvc_root / "infer_cli.py",
        rvc_root / "vc_infer_pipeline.py",
        *(rvc_root / path for path in required_rvc_training_paths()),
    )


def required_distribution_files(distribution: Path) -> tuple[Path, ...]:
    return required_application_files(distribution) + required_runtime_files(distribution)


def _verify_demucs_runtime(distribution: Path, runtime_python: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="jjzero-demucs-smoke-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "input.wav"
        output = temporary_root / "output"
        _write_test_audio(source)

        environment = os.environ.copy()
        environment["TORCH_HOME"] = str(
            distribution / "runtime" / "demucs" / "torch"
        )
        try:
            completed = subprocess.run(
                [
                    str(runtime_python),
                    "-m",
                    "demucs",
                    "--two-stems=vocals",
                    "-n",
                    "htdemucs",
                    "-d",
                    "cuda",
                    "-o",
                    str(output),
                    str(source),
                ],
                cwd=distribution,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            output_text = error.stdout or ""
            print("Packaged Demucs separation timed out after 120 seconds:", file=sys.stderr)
            print("\n".join(output_text.splitlines()[-20:]), file=sys.stderr)
            return False
        job_dir = output / "htdemucs" / source.stem
        expected = (job_dir / "vocals.wav", job_dir / "no_vocals.wav")
        if completed.returncode == 0 and all(path.is_file() for path in expected):
            return True
        print("Packaged Demucs separation failed:", file=sys.stderr)
        print("\n".join(completed.stdout.splitlines()[-20:]), file=sys.stderr)
        return False


def _write_test_audio(path: Path) -> None:
    sample_rate = 44_100
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate):
            value = int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<hh", value, value))
        audio.writeframes(frames)


def _verify_rvc_runtime(distribution: Path) -> bool:
    rvc_root = distribution / "runtime" / "rvc"
    runtime_python = rvc_root / "runtime" / "python.exe"
    command = (
        "import sys; "
        "sys.path.insert(0, '.'); "
        "import torch; "
        "import fairseq; "
        "import faiss; "
        "import lib.jjzero_device; "
        "import lib.infer_pack.models; "
        "import vc_infer_pipeline; "
        "sys.path.insert(0, 'runtime/jjzero-roformer-packages'); "
        "import audio_separator; "
        "assert torch.cuda.is_available(); "
        "print(torch.__version__)"
    )
    try:
        completed = subprocess.run(
            [str(runtime_python), "-c", command],
            cwd=rvc_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        print("Packaged RVC runtime check timed out after 90 seconds.", file=sys.stderr)
        return False
    if completed.returncode == 0:
        return True
    print("Packaged RVC runtime check failed:", file=sys.stderr)
    print("\n".join(completed.stdout.splitlines()[-20:]), file=sys.stderr)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
