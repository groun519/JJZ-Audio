from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path


DIRECTML_RMVPE_PROBE_DEVICE = "privateuseone:0"
_DIRECTML_RMVPE_PROBE_FREQUENCY_HZ = 440.0
_DIRECTML_RMVPE_PROBE_SAMPLE_RATE = 16_000
_DIRECTML_RMVPE_PROBE_SECONDS = 1
_DIRECTML_RMVPE_EXPECTED_OUTPUTS = (
    Path("2a_f0") / "probe.wav.npy",
    Path("2b-f0nsf") / "probe.wav.npy",
)


def create_directml_rmvpe_probe() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="jjz-directml-rmvpe-")
    root = Path(temporary.name)
    input_dir = root / "1_16k_wavs"
    input_dir.mkdir(parents=True, exist_ok=True)
    _write_probe_wave(input_dir / "probe.wav")
    return temporary, root


def directml_rmvpe_probe_command(
    python: Path,
    runtime_root: Path,
    probe_root: Path,
    *,
    device: str = DIRECTML_RMVPE_PROBE_DEVICE,
) -> list[str]:
    return [
        str(python),
        str(runtime_root / "extract_f0_rmvpe.py"),
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
