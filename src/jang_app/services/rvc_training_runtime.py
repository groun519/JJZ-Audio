from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from jang_app.services.rvc_cuda_compatibility import (
    cuda_architecture_error,
    parse_cuda_arch_list,
    parse_cuda_capability,
)
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_runtime_profile import RVC_PROFILE_DIRECTML
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_CU118,
    RVC_PROFILE_CU128,
    RVC_PROFILE_ROCM_WINDOWS,
    normalize_rvc_profile,
)


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
RVC_TRAINING_MODULE_FILES = (
    Path("lib/jjzero_device.py"),
    Path("lib/i18n/en_US.json"),
    Path("lib/train/utils.py"),
    Path("lib/infer_pack/models.py"),
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
    *RVC_TRAINING_MODULE_FILES,
    *RVC_TRAINING_ASSET_FILES,
)

_RUNTIME_PROBE = (
    "import json, torch; "
    "cpu_tensor=torch.arange(256, dtype=torch.float32).reshape(16, 16); "
    "cpu_ready=bool(torch.isfinite(cpu_tensor @ cpu_tensor.T).all().item()); "
    "available=torch.cuda.is_available(); count=torch.cuda.device_count(); "
    "print(json.dumps({'cpu_ready': cpu_ready, 'available': available, 'device_count': count, "
    "'torch_version': torch.__version__, 'cuda_version': torch.version.cuda or '', "
    "'hip_version': getattr(torch.version, 'hip', '') or '', "
    "'device_capability': list(torch.cuda.get_device_capability(0)) if available and count else [], "
    "'cuda_arch_list': list(torch.cuda.get_arch_list())}))"
)


@dataclass(frozen=True)
class RvcTrainingRuntimeInspection:
    root: Path
    missing_paths: tuple[Path, ...]
    cuda_available: bool | None = None
    cuda_device_count: int = 0
    cuda_error: str = ""
    torch_version: str = ""
    cuda_version: str = ""
    device_capability: tuple[int, int] = ()
    cpu_ready: bool | None = None
    backend: RvcComputeBackend = RvcComputeBackend.CPU
    hip_version: str = ""

    @property
    def assets_ready(self) -> bool:
        return not self.missing_paths

    @property
    def ready(self) -> bool:
        cpu_valid = self.cpu_ready is True or (
            self.cpu_ready is None and self.cuda_available is True
        )
        return self.assets_ready and cpu_valid and not self.cuda_error

    @property
    def accelerator_ready(self) -> bool:
        return self.cuda_available is True and not self.cuda_error and self.cuda_device_count > 0

    @property
    def training_accelerated(self) -> bool:
        backend = (
            RvcComputeBackend.CUDA
            if self.backend == RvcComputeBackend.CPU and self.cuda_available is True
            else self.backend
        )
        return self.accelerator_ready and backend in {
            RvcComputeBackend.CUDA,
            RvcComputeBackend.ROCM,
        }

    @property
    def feature_device(self) -> str:
        return "cuda:0" if self.training_accelerated else "cpu"

    @property
    def training_device(self) -> str:
        return "cuda:0" if self.training_accelerated else "cpu"


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
        [str(resolved_root / "runtime" / "python.exe"), "-c", _RUNTIME_PROBE],
        cwd=resolved_root,
    )
    if result.returncode != 0:
        return RvcTrainingRuntimeInspection(
            resolved_root,
            (),
            cuda_error=result.output or f"CUDA probe failed with exit code {result.returncode}.",
            backend=_profile_backend(resolved_root),
        )
    try:
        data = json.loads(_last_output_line(result.stdout))
        raw_available = data["available"]
        if not isinstance(raw_available, bool):
            raise TypeError("available must be a boolean")
        available = raw_available
        raw_cpu_ready = data.get("cpu_ready", True)
        if not isinstance(raw_cpu_ready, bool):
            raise TypeError("cpu_ready must be a boolean")
        device_count = max(0, int(data["device_count"]))
        if available and device_count == 0:
            raise ValueError("CUDA was reported available without a device")
        torch_version = str(data.get("torch_version", "")).strip()
        cuda_version = str(data.get("cuda_version", "")).strip()
        device_capability = parse_cuda_capability(data.get("device_capability"))
        cuda_arch_list = parse_cuda_arch_list(data.get("cuda_arch_list"))
        hip_version = str(data.get("hip_version", "")).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return RvcTrainingRuntimeInspection(
            resolved_root,
            (),
            cuda_error=f"CUDA probe returned an invalid response: {exc}",
            backend=_profile_backend(resolved_root),
        )
    compatibility_error = cuda_architecture_error(
        torch_version,
        cuda_version,
        device_capability,
        cuda_arch_list,
    )
    profile_backend = _profile_backend(resolved_root)
    backend = (
        RvcComputeBackend.ROCM
        if hip_version
        else RvcComputeBackend.CUDA
        if available
        else profile_backend
    )
    return RvcTrainingRuntimeInspection(
        resolved_root,
        (),
        cuda_available=available,
        cuda_device_count=device_count,
        cuda_error=compatibility_error,
        torch_version=torch_version,
        cuda_version=cuda_version,
        device_capability=device_capability,
        cpu_ready=raw_cpu_ready,
        backend=backend,
        hip_version=hip_version,
    )


def required_rvc_training_paths() -> tuple[Path, ...]:
    return _REQUIRED_PATHS


def training_backend_for_profile(profile: object) -> RvcComputeBackend:
    normalized = normalize_rvc_profile(profile)
    if normalized in {RVC_PROFILE_CU118, RVC_PROFILE_CU128}:
        return RvcComputeBackend.CUDA
    if normalized == RVC_PROFILE_ROCM_WINDOWS:
        return RvcComputeBackend.ROCM
    return RvcComputeBackend.CPU


def _last_output_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _profile_backend(root: Path) -> RvcComputeBackend:
    state = root / "runtime" / "jjzero-runtime-profile.json"
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return RvcComputeBackend.CPU
    profile = str(data.get("profile", "")).strip().lower() if isinstance(data, dict) else ""
    if profile == RVC_PROFILE_DIRECTML:
        return RvcComputeBackend.DIRECTML
    return training_backend_for_profile(profile)
