from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


class CommandResultLike(Protocol):
    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str: ...


RVC_TRAINING_VERSION = "v2"
RVC_TRAINING_SAMPLE_RATE = 40000
RVC_TRAINING_F0_METHOD = "rmvpe"
RVC_TRAINING_SCRIPT_FILES = (
    Path("extract_f0_rmvpe.py"),
    Path("extract_feature_print.py"),
    Path("train_nsf_sim_cache_sid_load_pretrain.py"),
)
RVC_TRAINING_ASSET_FILES = (
    Path("pretrained_v2/f0G40k.pth"),
    Path("pretrained_v2/f0D40k.pth"),
    Path("logs/mute/0_gt_wavs/mute40k.wav"),
    Path("logs/mute/0_gt_wavs/mute40k.spec.pt"),
    Path("logs/mute/2a_f0/mute.wav.npy"),
    Path("logs/mute/2b-f0nsf/mute.wav.npy"),
    Path("logs/mute/3_feature768/mute.npy"),
)

_REQUIRED_PATHS = (
    Path("runtime/python.exe"),
    Path("configs/40k.json"),
    Path("hubert_base.pt"),
    Path("rmvpe.pt"),
    Path("trainset_preprocess_pipeline_print.py"),
    *RVC_TRAINING_SCRIPT_FILES,
    *RVC_TRAINING_ASSET_FILES,
)

_CUDA_PROBE = (
    "import json, torch; "
    "print(json.dumps({'available': torch.cuda.is_available(), "
    "'device_count': torch.cuda.device_count()}))"
)


@dataclass(frozen=True)
class RvcTrainingRuntimeInspection:
    root: Path
    missing_paths: tuple[Path, ...]
    cuda_available: bool | None = None
    cuda_device_count: int = 0
    cuda_error: str = ""

    @property
    def assets_ready(self) -> bool:
        return not self.missing_paths

    @property
    def ready(self) -> bool:
        return self.assets_ready and self.cuda_available is True and not self.cuda_error


def inspect_rvc_training_runtime(
    root: Path,
    *,
    check_cuda: bool = False,
    command_runner: Callable[..., CommandResultLike] | None = None,
) -> RvcTrainingRuntimeInspection:
    resolved_root = root.expanduser().resolve()
    missing = tuple(path for path in _REQUIRED_PATHS if not (resolved_root / path).is_file())
    if missing or not check_cuda:
        return RvcTrainingRuntimeInspection(resolved_root, missing)

    if command_runner is None:
        from jang_app.services.command import run_command

        command_runner = run_command
    result = command_runner(
        [str(resolved_root / "runtime" / "python.exe"), "-c", _CUDA_PROBE],
        cwd=resolved_root,
    )
    if result.returncode != 0:
        return RvcTrainingRuntimeInspection(
            resolved_root,
            (),
            cuda_error=result.output or f"CUDA probe failed with exit code {result.returncode}.",
        )
    try:
        data = json.loads(_last_output_line(result.stdout))
        raw_available = data["available"]
        if not isinstance(raw_available, bool):
            raise TypeError("available must be a boolean")
        available = raw_available
        device_count = max(0, int(data["device_count"]))
        if available and device_count == 0:
            raise ValueError("CUDA was reported available without a device")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return RvcTrainingRuntimeInspection(
            resolved_root,
            (),
            cuda_error=f"CUDA probe returned an invalid response: {exc}",
        )
    return RvcTrainingRuntimeInspection(
        resolved_root,
        (),
        cuda_available=available,
        cuda_device_count=device_count,
    )


def required_rvc_training_paths() -> tuple[Path, ...]:
    return _REQUIRED_PATHS


def _last_output_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""
