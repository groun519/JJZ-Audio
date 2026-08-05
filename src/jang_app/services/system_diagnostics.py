from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.rvc_inference_runtime import (
    RvcInferenceCapabilities,
    probe_rvc_inference_runtime,
)
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


RuntimeProbe = Callable[[Path], RvcInferenceCapabilities]
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

    capabilities = (runtime_probe or probe_rvc_inference_runtime)(rvc_root)
    runtime_check, cuda_check = _runtime_checks(capabilities)
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


def _runtime_checks(capabilities: RvcInferenceCapabilities) -> tuple[DiagnosticCheck, DiagnosticCheck]:
    version = f" (Torch {capabilities.torch_version})" if capabilities.torch_version else ""
    runtime = DiagnosticCheck(
        "ai_runtime",
        "AI Runtime",
        DiagnosticStatus.PASS if capabilities.runtime_ready else DiagnosticStatus.FAIL,
        f"CPU inference and FAISS ready{version}"
        if capabilities.runtime_ready
        else capabilities.cpu_detail or "CPU inference or FAISS validation failed.",
    )
    if capabilities.cuda_ready and capabilities.device_count > 0:
        cuda = DiagnosticCheck(
            "cuda",
            "NVIDIA GPU",
            DiagnosticStatus.PASS,
            capabilities.device_name or f"CUDA devices: {capabilities.device_count}",
        )
    elif capabilities.cuda_available:
        detail = capabilities.cuda_detail or "CUDA operation failed. CPU conversion will be used."
        cuda = DiagnosticCheck("cuda", "NVIDIA GPU", DiagnosticStatus.WARNING, detail)
    else:
        cuda = DiagnosticCheck(
            "cuda",
            "NVIDIA GPU",
            DiagnosticStatus.WARNING,
            "CUDA is unavailable. CPU conversion will be used.",
        )
    return runtime, cuda
