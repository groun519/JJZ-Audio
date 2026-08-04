from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


EXECUTABLE_NAME = "JJZero Audio.exe"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_distribution.py <distribution-directory>", file=sys.stderr)
        return 2

    distribution = Path(sys.argv[1]).expanduser().resolve()
    executable = distribution / EXECUTABLE_NAME
    rvc_python = distribution / "runtime" / "rvc" / "runtime" / "python.exe"
    required_files = (
        executable,
        rvc_python,
        distribution / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
        distribution / "runtime" / "ffmpeg" / "bin" / "ffprobe.exe",
        distribution
        / "runtime"
        / "demucs"
        / "torch"
        / "hub"
        / "checkpoints"
        / "955717e8-8726e21a.th",
        distribution / "runtime" / "rvc" / "infer_cli.py",
        distribution / "runtime" / "rvc" / "vc_infer_pipeline.py",
        distribution / "runtime" / "rvc" / "hubert_base.pt",
        distribution / "runtime" / "rvc" / "rmvpe.pt",
        distribution / "_internal" / "jang_app" / "assets" / "jjzero_logo.svg",
    )
    missing = tuple(path for path in required_files if not path.is_file())
    if missing:
        for path in missing:
            print(f"Missing distribution file: {path}", file=sys.stderr)
        return 1

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

    print(f"Verified distribution: {distribution}")
    return 0


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
        "import lib.infer_pack.models; "
        "import vc_infer_pipeline; "
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
