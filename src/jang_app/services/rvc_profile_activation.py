from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jang_app.services.app_logging import get_logger
from jang_app.services.command import background_command_args, hidden_subprocess_kwargs
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_CU118,
    RVC_PROFILE_CU128,
    RVC_PROFILE_DIRECTML,
    RVC_PROFILE_ROCM_WINDOWS,
    normalize_rvc_profile,
)


class CommandResultLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


ActivationCommandRunner = Callable[[Sequence[str], Path], CommandResultLike]


@dataclass(frozen=True)
class RvcProfileActivation:
    profile: str
    backend: str
    device_name: str
    torch_version: str
    accelerator_version: str


class RvcProfileActivationError(RuntimeError):
    pass


def validate_rvc_profile_activation(
    profile: str,
    runtime_root: Path,
    *,
    command_runner: ActivationCommandRunner | None = None,
) -> RvcProfileActivation:
    normalized = normalize_rvc_profile(profile)
    if normalized not in {
        RVC_PROFILE_CU118,
        RVC_PROFILE_CU128,
        RVC_PROFILE_DIRECTML,
        RVC_PROFILE_ROCM_WINDOWS,
    }:
        return RvcProfileActivation(normalized, "cpu", "CPU", "", "")
    root = runtime_root.expanduser().resolve()
    python = root / "python.exe"
    if not python.is_file():
        raise RvcProfileActivationError(f"RVC {normalized} runtime has no python.exe.")
    runner = command_runner or _run_command
    result = runner((str(python), "-c", _activation_probe(normalized)), root)
    output = "\n".join(value for value in (result.stdout, result.stderr) if value.strip())
    if result.returncode != 0:
        raise RvcProfileActivationError(
            f"RVC {normalized} activation probe exited with code {result.returncode}: "
            f"{_last_line(output)}"
        )
    try:
        data = json.loads(_last_json_line(result.stdout))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RvcProfileActivationError(
            f"RVC {normalized} activation probe returned invalid data: {_last_line(output)}"
        ) from exc
    if not isinstance(data, dict) or data.get("ready") is not True:
        detail = str(data.get("detail", "")).strip() if isinstance(data, dict) else ""
        raise RvcProfileActivationError(
            f"RVC {normalized} activation failed: {detail or _last_line(output)}"
        )
    activation = RvcProfileActivation(
        normalized,
        str(data.get("backend", "")),
        str(data.get("device_name", "")),
        str(data.get("torch", "")),
        str(data.get("accelerator", "")),
    )
    get_logger().info(
        "RVC profile activation passed: profile=%s backend=%s device=%s torch=%s accelerator=%s",
        activation.profile,
        activation.backend,
        activation.device_name,
        activation.torch_version,
        activation.accelerator_version,
    )
    return activation


def _activation_probe(profile: str) -> str:
    return f"""
import json

result = {{
    "ready": False,
    "backend": "",
    "device_name": "",
    "torch": "",
    "accelerator": "",
    "detail": "",
}}
try:
    import faiss
    import fairseq
    import torch
    import torchaudio

    result["torch"] = str(torch.__version__)
    profile = {profile!r}
    if profile == "directml":
        import torch_directml

        index = int(torch_directml.default_device())
        device = torch_directml.device(index)
        result["backend"] = "directml"
        result["accelerator"] = str(getattr(torch_directml, "__version__", ""))
        try:
            result["device_name"] = str(torch_directml.device_name(index))
        except BaseException:
            result["device_name"] = f"DirectML device {{index}}"
    else:
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            raise RuntimeError("PyTorch did not expose a GPU device")
        device = torch.device("cuda:0")
        hip = str(getattr(torch.version, "hip", "") or "")
        if profile == "rocm-win" and not hip:
            raise RuntimeError("PyTorch has no HIP runtime")
        if profile != "rocm-win" and hip:
            raise RuntimeError("CUDA profile unexpectedly loaded a HIP runtime")
        result["backend"] = "rocm" if hip else "cuda"
        result["accelerator"] = hip or str(torch.version.cuda or "")
        result["device_name"] = str(torch.cuda.get_device_name(0))

    left = torch.arange(1024, dtype=torch.float32).reshape(32, 32).to(device)
    conv1 = torch.nn.Conv1d(4, 8, kernel_size=3, padding=1).to(device)
    conv2 = torch.nn.Conv2d(1, 4, kernel_size=3, padding=1).to(device)
    input1 = torch.randn(1, 4, 128, device=device)
    input2 = torch.randn(1, 1, 32, 32, device=device)
    values = (left @ left.T, conv1(input1), conv2(input2))
    loss = values[1].square().mean() + values[2].square().mean()
    if result["backend"] in {{"cuda", "rocm"}}:
        torch.cuda.synchronize(0)
    result["ready"] = bool(torch.isfinite(loss.detach().cpu()).item()) and all(
        bool(torch.isfinite(value.detach().cpu()).all().item()) for value in values
    )
except BaseException as exc:
    result["detail"] = f"{{type(exc).__name__}}: {{exc}}"
print(json.dumps(result, ensure_ascii=False))
""".strip()


def _run_command(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            background_command_args(args),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(args), 1, "", str(exc))


def _last_json_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
    return ""


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "No process output"
