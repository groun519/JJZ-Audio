from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jang_app.services.rvc_environment import build_rvc_environment


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

    @property
    def runtime_ready(self) -> bool:
        return self.imports_ready and self.cpu_ready and self.faiss_ready


@dataclass(frozen=True)
class RvcDeviceSelection:
    requested_device: str
    effective_device: str
    capabilities: RvcInferenceCapabilities
    fallback_reason: str = ""


class RvcInferenceRuntimeError(RuntimeError):
    """Raised when the bundled RVC runtime cannot perform CPU inference."""


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

    requested = requested_device.strip().lower() or "cpu"
    if requested == "cpu":
        return RvcDeviceSelection(requested, "cpu", capabilities)

    match = re.fullmatch(r"cuda(?::(?P<index>\d+))?", requested)
    if match is None:
        return RvcDeviceSelection(requested, "cpu", capabilities, "Unsupported device setting; using CPU.")

    index = int(match.group("index") or 0)
    if capabilities.cuda_ready and index < capabilities.device_count:
        return RvcDeviceSelection(requested, f"cuda:{index}", capabilities)

    reason = capabilities.cuda_detail or "CUDA is unavailable; using CPU."
    return RvcDeviceSelection(requested, "cpu", capabilities, reason)


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

    cuda_result = _run_probe(python, root, _CUDA_PROBE)
    cuda_data, cuda_error = _parse_probe_result(cuda_result, "CUDA inference")
    cuda_data = cuda_data or {}
    return RvcInferenceCapabilities(
        imports_ready=bool(cpu_data.get("imports_ready")),
        cpu_ready=bool(cpu_data.get("cpu_ready")),
        faiss_ready=bool(cpu_data.get("faiss_ready")),
        cuda_available=bool(cuda_data.get("cuda_available")),
        cuda_ready=bool(cuda_data.get("cuda_ready")),
        device_count=_safe_int(cuda_data.get("device_count")),
        device_name=str(cuda_data.get("device_name", "")).strip(),
        torch_version=str(cpu_data.get("torch_version", "")).strip(),
        cpu_detail=str(cpu_data.get("detail", "")).strip(),
        cuda_detail=cuda_error or str(cuda_data.get("detail", "")).strip(),
    )


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
            [str(python), "-c", script],
            cwd=rvc_root,
            env=build_rvc_environment(rvc_root),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    "detail": "",
}
try:
    import torch

    result["cuda_available"] = bool(torch.cuda.is_available())
    result["device_count"] = int(torch.cuda.device_count())
    if result["cuda_available"] and result["device_count"]:
        result["device_name"] = torch.cuda.get_device_name(0)
        left = torch.arange(1024, dtype=torch.float32, device="cuda:0").reshape(32, 32)
        product = left @ left.T
        torch.cuda.synchronize(0)
        result["cuda_ready"] = bool(torch.isfinite(product).all().item())
except BaseException as exc:
    result["detail"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False))
""".strip()
