from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jang_app.services.command import background_command_args, hidden_subprocess_kwargs
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_cuda_compatibility import (
    cuda_architecture_error,
    parse_cuda_arch_list,
    parse_cuda_capability,
)
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_runtime_profile import RVC_PROFILE_DIRECTML


@dataclass(frozen=True)
class RvcInferenceCapabilities:
    imports_ready: bool
    cpu_ready: bool
    faiss_ready: bool
    cuda_available: bool
    cuda_ready: bool
    device_count: int = 0
    device_name: str = ""
    torch_version: str = ""
    cpu_detail: str = ""
    cuda_detail: str = ""
    cuda_version: str = ""
    device_capability: tuple[int, int] = ()
    cuda_arch_list: tuple[str, ...] = ()
    hip_version: str = ""
    directml_available: bool = False
    directml_ready: bool = False
    directml_device: str = "privateuseone:0"
    directml_device_name: str = ""
    directml_detail: str = ""

    @property
    def runtime_ready(self) -> bool:
        return self.imports_ready and self.cpu_ready and self.faiss_ready

    @property
    def accelerator_backend(self) -> RvcComputeBackend:
        if self.directml_ready:
            return RvcComputeBackend.DIRECTML
        if self.cuda_ready:
            return RvcComputeBackend.ROCM if self.hip_version else RvcComputeBackend.CUDA
        return RvcComputeBackend.CPU

    @property
    def accelerator_ready(self) -> bool:
        return self.directml_ready or self.cuda_ready

    @property
    def accelerator_detail(self) -> str:
        return self.directml_detail if self.directml_available else self.cuda_detail


@dataclass(frozen=True)
class RvcDeviceSelection:
    requested_device: str
    effective_device: str
    capabilities: RvcInferenceCapabilities
    fallback_reason: str = ""


class RvcInferenceRuntimeError(RuntimeError):
    """Raised when the bundled RVC runtime cannot honor the requested device."""


RuntimeProbe = Callable[[Path], RvcInferenceCapabilities]


def probe_rvc_inference_runtime(rvc_root: Path) -> RvcInferenceCapabilities:
    root = rvc_root.expanduser().resolve()
    return _probe_rvc_inference_runtime_cached(str(root))


def clear_rvc_inference_probe_cache() -> None:
    _probe_rvc_inference_runtime_cached.cache_clear()


def select_rvc_inference_device(
    rvc_root: Path,
    requested_device: str,
    *,
    runtime_probe: RuntimeProbe = probe_rvc_inference_runtime,
) -> RvcDeviceSelection:
    capabilities = runtime_probe(rvc_root)
    if not capabilities.runtime_ready:
        detail = capabilities.cpu_detail or "CPU inference or FAISS validation failed."
        raise RvcInferenceRuntimeError(f"RVC inference runtime is not compatible with this PC: {detail}")

    requested = requested_device.strip().lower() or "auto"
    if requested == "cpu":
        return RvcDeviceSelection(requested, "cpu", capabilities)

    if requested in {"directml", "dml", "privateuseone", "privateuseone:0"}:
        if capabilities.directml_ready:
            return RvcDeviceSelection(requested, capabilities.directml_device, capabilities)
        detail = capabilities.directml_detail or (
            "DirectML GPU acceleration is unavailable. Repair the DirectML runtime "
            "or select CPU explicitly."
        )
        raise RvcInferenceRuntimeError(detail)

    match = re.fullmatch(r"cuda(?::(?P<index>\d+))?", requested)
    is_automatic = requested in {"auto", "gpu", "accelerator"}
    if match is None and not is_automatic:
        return RvcDeviceSelection(requested, "cpu", capabilities, "Unsupported device setting; using CPU.")

    if capabilities.directml_ready:
        return RvcDeviceSelection(requested, capabilities.directml_device, capabilities)

    if capabilities.device_capability >= (12, 0) and not capabilities.cuda_ready:
        detail = capabilities.cuda_detail or (
            "RTX 50-series CUDA validation failed. Install or repair the cu128 AI runtime."
        )
        raise RvcInferenceRuntimeError(detail)

    index = int(match.group("index") or 0) if match is not None else 0
    if capabilities.cuda_ready and index < capabilities.device_count:
        return RvcDeviceSelection(requested, f"cuda:{index}", capabilities)

    reason = capabilities.accelerator_detail or "GPU acceleration is unavailable."
    if requested == "auto":
        return RvcDeviceSelection(requested, "cpu", capabilities, reason)
    raise RvcInferenceRuntimeError(
        f"{reason} Select CPU explicitly if GPU acceleration is not required."
    )


@lru_cache(maxsize=4)
def _probe_rvc_inference_runtime_cached(rvc_root: str) -> RvcInferenceCapabilities:
    root = Path(rvc_root)
    python = root / "runtime" / "python.exe"
    if not python.is_file():
        return RvcInferenceCapabilities(
            imports_ready=False,
            cpu_ready=False,
            faiss_ready=False,
            cuda_available=False,
            cuda_ready=False,
            cpu_detail=f"RVC runtime Python was not found: {python}",
            cuda_detail="CUDA check was skipped.",
        )

    cpu_result = _run_probe(python, root, _CPU_PROBE)
    cpu_data, cpu_error = _parse_probe_result(cpu_result, "CPU inference")
    if cpu_data is None:
        return RvcInferenceCapabilities(
            imports_ready=False,
            cpu_ready=False,
            faiss_ready=False,
            cuda_available=False,
            cuda_ready=False,
            cpu_detail=cpu_error,
            cuda_detail="CUDA check was skipped.",
        )

    imports_ready = bool(cpu_data.get("imports_ready"))
    cpu_ready = bool(cpu_data.get("cpu_ready"))
    faiss_ready = bool(cpu_data.get("faiss_ready"))
    torch_version = str(cpu_data.get("torch_version", "")).strip()
    if not (imports_ready and cpu_ready and faiss_ready):
        return RvcInferenceCapabilities(
            imports_ready=imports_ready,
            cpu_ready=cpu_ready,
            faiss_ready=faiss_ready,
            cuda_available=False,
            cuda_ready=False,
            torch_version=torch_version,
            cpu_detail=str(cpu_data.get("detail", "")).strip(),
            cuda_detail="GPU check was skipped until CPU inference and FAISS are ready.",
        )

    profile = _installed_profile(root)
    accelerator_label = "DirectML inference" if profile == RVC_PROFILE_DIRECTML else "CUDA inference"
    accelerator_script = _DIRECTML_PROBE if profile == RVC_PROFILE_DIRECTML else _CUDA_PROBE
    cuda_result = _run_probe(python, root, accelerator_script)
    cuda_data, cuda_error = _parse_probe_result(cuda_result, accelerator_label)
    cuda_data = cuda_data or {}
    cuda_version = str(cuda_data.get("cuda_version", "")).strip()
    device_capability = parse_cuda_capability(cuda_data.get("device_capability"))
    cuda_arch_list = parse_cuda_arch_list(cuda_data.get("cuda_arch_list"))
    directml_profile = profile == RVC_PROFILE_DIRECTML
    cuda_ready = bool(cuda_data.get("cuda_ready")) if not directml_profile else False
    cuda_detail = cuda_error or str(cuda_data.get("detail", "")).strip()
    compatibility_error = cuda_architecture_error(
        torch_version,
        cuda_version,
        device_capability,
        cuda_arch_list,
    )
    if compatibility_error and not directml_profile:
        cuda_ready = False
        cuda_detail = " ".join(filter(None, (compatibility_error, cuda_detail, "Using CPU.")))
    return RvcInferenceCapabilities(
        imports_ready=imports_ready,
        cpu_ready=cpu_ready,
        faiss_ready=faiss_ready,
        cuda_available=bool(cuda_data.get("cuda_available")),
        cuda_ready=cuda_ready,
        device_count=_safe_int(cuda_data.get("device_count")),
        device_name=str(cuda_data.get("device_name", "")).strip(),
        torch_version=torch_version,
        cpu_detail=str(cpu_data.get("detail", "")).strip(),
        cuda_detail=cuda_detail,
        cuda_version=cuda_version,
        device_capability=device_capability,
        cuda_arch_list=cuda_arch_list,
        hip_version=str(cuda_data.get("hip_version", "")).strip(),
        directml_available=bool(cuda_data.get("directml_available")),
        directml_ready=bool(cuda_data.get("directml_ready")),
        directml_device=str(cuda_data.get("directml_device", "privateuseone:0")).strip()
        or "privateuseone:0",
        directml_device_name=str(cuda_data.get("device_name", "")).strip(),
        directml_detail=(
            cuda_error or str(cuda_data.get("detail", "")).strip()
            if directml_profile
            else ""
        ),
    )


def _installed_profile(root: Path) -> str:
    state = root / "runtime" / "jjzero-runtime-profile.json"
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("profile", "")).strip().lower() if isinstance(data, dict) else ""


@dataclass(frozen=True)
class _ProbeResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stderr or self.stdout).strip()


def _run_probe(python: Path, rvc_root: Path, script: str) -> _ProbeResult:
    try:
        completed = subprocess.run(
            background_command_args([str(python), "-c", script]),
            cwd=rvc_root,
            env=build_rvc_environment(rvc_root),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _ProbeResult(1, "", str(exc))
    return _ProbeResult(completed.returncode, completed.stdout, completed.stderr)


def _parse_probe_result(result: _ProbeResult, label: str) -> tuple[dict[str, object] | None, str]:
    if result.returncode != 0:
        return None, _process_failure_detail(label, result.returncode, result.output)
    try:
        data = json.loads(_last_line(result.stdout))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, f"{label} probe returned invalid data: {exc}"
    if not isinstance(data, dict):
        return None, f"{label} probe returned invalid data."
    return data, ""


def _process_failure_detail(label: str, returncode: int, output: str) -> str:
    windows_code = returncode & 0xFFFFFFFF
    if windows_code == 0xC0000094:
        return (
            f"{label} crashed with Windows status 0xC0000094 (integer divide by zero). "
            "The bundled Torch runtime is incompatible with this CPU."
        )
    detail = _last_line(output)
    code = f"{returncode} (0x{windows_code:08X})" if returncode else "0"
    return detail or f"{label} probe failed with exit code {code}."


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


_CPU_PROBE = """
import json

result = {
    "imports_ready": False,
    "cpu_ready": False,
    "faiss_ready": False,
    "torch_version": "",
    "detail": "",
}
try:
    import numpy as np
    import torch
    import fairseq
    import faiss

    result["imports_ready"] = True
    result["torch_version"] = torch.__version__
    left = torch.arange(1024, dtype=torch.float32, device="cpu").reshape(32, 32)
    product = left @ left.T
    result["cpu_ready"] = bool(torch.isfinite(product).all().item())

    vectors = np.arange(32, dtype=np.float32).reshape(8, 4)
    index = faiss.IndexFlatL2(4)
    index.add(vectors)
    distances, neighbors = index.search(vectors[:1], 2)
    result["faiss_ready"] = neighbors.shape == (1, 2) and distances.shape == (1, 2)
except BaseException as exc:
    result["detail"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False))
""".strip()


_CUDA_PROBE = """
import json

result = {
    "cuda_available": False,
    "cuda_ready": False,
    "device_count": 0,
    "device_name": "",
    "cuda_version": "",
    "device_capability": [],
    "cuda_arch_list": [],
    "hip_version": "",
    "detail": "",
}
try:
    import torch

    result["cuda_available"] = bool(torch.cuda.is_available())
    result["device_count"] = int(torch.cuda.device_count())
    result["cuda_version"] = str(torch.version.cuda or "")
    result["hip_version"] = str(getattr(torch.version, "hip", "") or "")
    result["cuda_arch_list"] = list(torch.cuda.get_arch_list())
    if result["cuda_available"] and result["device_count"]:
        result["device_name"] = torch.cuda.get_device_name(0)
        result["device_capability"] = list(torch.cuda.get_device_capability(0))
        left = torch.arange(1024, dtype=torch.float32, device="cuda:0").reshape(32, 32)
        product = left @ left.T
        conv1d = torch.nn.Conv1d(4, 8, kernel_size=3, padding=1).to("cuda:0")
        conv2d = torch.nn.Conv2d(1, 4, kernel_size=3, padding=1).to("cuda:0")
        one_d = conv1d(torch.randn(1, 4, 128, device="cuda:0"))
        two_d = conv2d(torch.randn(1, 1, 32, 32, device="cuda:0"))
        torch.cuda.synchronize(0)
        result["cuda_ready"] = all(
            bool(torch.isfinite(value).all().item())
            for value in (product, one_d, two_d)
        )
except BaseException as exc:
    result["detail"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False))
""".strip()


_DIRECTML_PROBE = """
import json
from pathlib import Path

result = {
    "directml_available": False,
    "directml_ready": False,
    "directml_device": "privateuseone:0",
    "device_name": "",
    "detail": "",
}
try:
    import onnxruntime as ort
    import torch
    import torch_directml

    result["directml_available"] = True
    providers = list(ort.get_available_providers())
    if "DmlExecutionProvider" not in providers:
        raise RuntimeError(
            f"ONNX Runtime has no DmlExecutionProvider: {providers}"
        )
    rmvpe_model = next(
        (path for path in (Path("runtime/rmvpe.onnx"), Path("rmvpe.onnx")) if path.is_file()),
        None,
    )
    if rmvpe_model is None or rmvpe_model.stat().st_size <= 0:
        raise RuntimeError("DirectML RMVPE model is missing: rmvpe.onnx")
    index = int(torch_directml.default_device())
    device = torch_directml.device(index)
    result["directml_device"] = str(device)
    try:
        result["device_name"] = str(torch_directml.device_name(index))
    except BaseException:
        result["device_name"] = f"DirectML device {index}"
    left = torch.arange(1024, dtype=torch.float32).reshape(32, 32).to(device)
    product = left @ left.T
    conv1d = torch.nn.Conv1d(4, 8, kernel_size=3, padding=1).to(device)
    conv2d = torch.nn.Conv2d(1, 4, kernel_size=3, padding=1).to(device)
    one_d = conv1d(torch.randn(1, 4, 128).to(device))
    two_d = conv2d(torch.randn(1, 1, 32, 32).to(device))
    result["directml_ready"] = all(
        bool(torch.isfinite(value.cpu()).all().item())
        for value in (product, one_d, two_d)
    )
except BaseException as exc:
    result["detail"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False))
""".strip()
