from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class DiagnosticStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class DiagnosticCheck:
    key: str
    title: str
    status: DiagnosticStatus
    detail: str


@dataclass(frozen=True)
class SystemDiagnostics:
    checks: tuple[DiagnosticCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.status != DiagnosticStatus.FAIL for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == DiagnosticStatus.WARNING for check in self.checks)


@dataclass(frozen=True)
class DiagnosticCommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stderr or self.stdout).strip()


RuntimeProbe = Callable[[Path], DiagnosticCommandResult]
DiagnosticReporter = Callable[[DiagnosticCheck], None]


def run_system_diagnostics(
    paths: AppPaths,
    *,
    runtime_probe: RuntimeProbe | None = None,
    reporter: DiagnosticReporter | None = None,
) -> SystemDiagnostics:
    checks: list[DiagnosticCheck] = []

    def record(check: DiagnosticCheck) -> None:
        checks.append(check)
        if reporter is not None:
            reporter(check)

    record(_storage_check(paths))
    record(_file_pair_check("ffmpeg", "FFmpeg", paths.runtime_root / "ffmpeg" / "bin"))
    record(_demucs_check(paths.runtime_root))
    rvc_root = paths.runtime_root / "rvc"
    assets = _rvc_assets_check(rvc_root)
    record(assets)
    if assets.status == DiagnosticStatus.FAIL:
        record(DiagnosticCheck("ai_runtime", "AI Runtime", DiagnosticStatus.FAIL, "RVC runtime is incomplete."))
        record(DiagnosticCheck("cuda", "NVIDIA GPU", DiagnosticStatus.WARNING, "CUDA check was skipped."))
        return SystemDiagnostics(tuple(checks))

    result = (runtime_probe or _probe_rvc_runtime)(rvc_root)
    runtime_check, cuda_check = _runtime_checks(result)
    record(runtime_check)
    record(cuda_check)
    return SystemDiagnostics(tuple(checks))


def _storage_check(paths: AppPaths) -> DiagnosticCheck:
    required = (paths.data_root, paths.workspace_root, paths.output_root)
    missing = tuple(path for path in required if not path.is_dir())
    if missing:
        return DiagnosticCheck(
            "storage",
            "Storage",
            DiagnosticStatus.FAIL,
            f"Missing storage directory: {missing[0]}",
        )
    return DiagnosticCheck("storage", "Storage", DiagnosticStatus.PASS, str(paths.workspace_anchor))


def _file_pair_check(key: str, title: str, root: Path) -> DiagnosticCheck:
    missing = tuple(name for name in ("ffmpeg.exe", "ffprobe.exe") if not (root / name).is_file())
    if missing:
        return DiagnosticCheck(key, title, DiagnosticStatus.FAIL, f"Missing: {', '.join(missing)}")
    return DiagnosticCheck(key, title, DiagnosticStatus.PASS, "Bundled tools ready")


def _demucs_check(runtime_root: Path) -> DiagnosticCheck:
    model = runtime_root / "demucs" / "torch" / "hub" / "checkpoints" / "955717e8-8726e21a.th"
    if not model.is_file():
        return DiagnosticCheck("demucs", "Demucs", DiagnosticStatus.FAIL, "Separation model is missing.")
    return DiagnosticCheck("demucs", "Demucs", DiagnosticStatus.PASS, "Separation model ready")


def _rvc_assets_check(rvc_root: Path) -> DiagnosticCheck:
    required = (
        Path("infer_cli.py"),
        Path("vc_infer_pipeline.py"),
        *required_rvc_training_paths(),
    )
    missing = tuple(path for path in required if not (rvc_root / path).is_file())
    if missing:
        return DiagnosticCheck(
            "rvc_assets",
            "RVC Assets",
            DiagnosticStatus.FAIL,
            f"Missing: {missing[0].as_posix()}",
        )
    return DiagnosticCheck("rvc_assets", "RVC Assets", DiagnosticStatus.PASS, "Convert and training assets ready")


def _runtime_checks(result: DiagnosticCommandResult) -> tuple[DiagnosticCheck, DiagnosticCheck]:
    if result.returncode != 0:
        detail = _last_line(result.output) or f"Runtime probe failed with exit code {result.returncode}."
        return (
            DiagnosticCheck("ai_runtime", "AI Runtime", DiagnosticStatus.FAIL, detail),
            DiagnosticCheck("cuda", "NVIDIA GPU", DiagnosticStatus.WARNING, "CUDA check failed."),
        )
    try:
        data = json.loads(_last_line(result.stdout))
        imports_ready = bool(data["imports_ready"])
        cuda_available = bool(data["cuda_available"])
        device_count = int(data["device_count"])
        device_name = str(data.get("device_name", "")).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            DiagnosticCheck("ai_runtime", "AI Runtime", DiagnosticStatus.FAIL, f"Invalid runtime response: {exc}"),
            DiagnosticCheck("cuda", "NVIDIA GPU", DiagnosticStatus.WARNING, "CUDA check failed."),
        )

    runtime = DiagnosticCheck(
        "ai_runtime",
        "AI Runtime",
        DiagnosticStatus.PASS if imports_ready else DiagnosticStatus.FAIL,
        "Torch, Fairseq, and FAISS ready" if imports_ready else "Required Python modules could not be imported.",
    )
    if cuda_available and device_count > 0:
        cuda = DiagnosticCheck(
            "cuda",
            "NVIDIA GPU",
            DiagnosticStatus.PASS,
            device_name or f"CUDA devices: {device_count}",
        )
    else:
        cuda = DiagnosticCheck(
            "cuda",
            "NVIDIA GPU",
            DiagnosticStatus.WARNING,
            "CUDA is unavailable. Update the NVIDIA graphics driver.",
        )
    return runtime, cuda


def _probe_rvc_runtime(rvc_root: Path) -> DiagnosticCommandResult:
    python = rvc_root / "runtime" / "python.exe"
    command = (
        "import json, torch; "
        "import fairseq, faiss; "
        "available=torch.cuda.is_available(); "
        "count=torch.cuda.device_count(); "
        "name=torch.cuda.get_device_name(0) if available and count else ''; "
        "print(json.dumps({'imports_ready': True, 'cuda_available': available, "
        "'device_count': count, 'device_name': name}, ensure_ascii=False))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", command],
            cwd=rvc_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DiagnosticCommandResult((str(python), "-c", command), 1, "", str(exc))
    return DiagnosticCommandResult(
        tuple(str(part) for part in completed.args),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""
