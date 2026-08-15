from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path

from jang_app.services.managed_files import link_or_copy_file


DIRECTML_RMVPE_PROBE_DEVICE = "privateuseone:0"
_DIRECTML_RMVPE_PROBE_FREQUENCY_HZ = 440.0
_DIRECTML_RMVPE_PROBE_SAMPLE_RATE = 16_000
_DIRECTML_RMVPE_PROBE_SECONDS = 1
_DIRECTML_RMVPE_EXPECTED_OUTPUTS = (
    Path("2a_f0") / "probe.wav.npy",
    Path("2b-f0nsf") / "probe.wav.npy",
)

_DIRECTML_RMVPE_BOOTSTRAP = """
import os
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
probe_root = Path(sys.argv[5]).resolve()
sys.path.insert(0, str(script.parent))
os.chdir(probe_root)
sys.argv = sys.argv[1:]
runpy.run_path(str(script), run_name="__main__")
""".strip()


def create_directml_rmvpe_probe() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="jjz-directml-rmvpe-")
    root = Path(temporary.name)
    input_dir = root / "1_16k_wavs"
    input_dir.mkdir(parents=True, exist_ok=True)
    _write_probe_wave(input_dir / "probe.wav")
    return temporary, root


def find_directml_rmvpe_model(runtime_root: Path) -> Path | None:
    candidates = (
        runtime_root / "runtime" / "rmvpe.onnx",
        runtime_root / "rmvpe.onnx",
    )
    return next((path for path in candidates if path.is_file()), None)


def stage_directml_rmvpe_probe_model(runtime_root: Path, probe_root: Path) -> Path:
    source = find_directml_rmvpe_model(runtime_root)
    if source is None:
        raise FileNotFoundError("The installed DirectML runtime is missing rmvpe.onnx.")
    return link_or_copy_file(source, probe_root / "rmvpe.onnx")


def directml_rmvpe_probe_command(
    python: Path,
    runtime_root: Path,
    probe_root: Path,
    *,
    device: str = DIRECTML_RMVPE_PROBE_DEVICE,
) -> list[str]:
    script = runtime_root / "extract_f0_rmvpe.py"
    return [
        str(python),
        "-c",
        _DIRECTML_RMVPE_BOOTSTRAP,
        str(script),
        "1",
        "0",
        device,
        str(probe_root),
        "True",
    ]


def missing_directml_rmvpe_outputs(probe_root: Path) -> tuple[str, ...]:
    return tuple(
        relative.as_posix()
        for relative in _DIRECTML_RMVPE_EXPECTED_OUTPUTS
        if not (probe_root / relative).is_file()
    )


def _write_probe_wave(path: Path) -> None:
    total_samples = _DIRECTML_RMVPE_PROBE_SAMPLE_RATE * _DIRECTML_RMVPE_PROBE_SECONDS
    frames = bytearray()
    for index in range(total_samples):
        value = int(
            0.18
            * 32767
            * math.sin(
                (2.0 * math.pi * _DIRECTML_RMVPE_PROBE_FREQUENCY_HZ * index)
                / _DIRECTML_RMVPE_PROBE_SAMPLE_RATE
            )
        )
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(_DIRECTML_RMVPE_PROBE_SAMPLE_RATE)
        output.writeframes(bytes(frames))
