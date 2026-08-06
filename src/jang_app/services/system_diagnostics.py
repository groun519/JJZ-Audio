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
from jang_app.services.runtime_installation import (
    RUNTIME_STATE_NAME,
    installed_rvc_runtime_profile,
)
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_CU128,
    RVC_PROFILE_DIRECTML,
    RVC_PROFILE_ROCM_WINDOWS,
    detect_rvc_runtime_profile,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class DiagnosticStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    REQUIRED = "required"
    SKIPPED = "skipped"
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
        blocking = {DiagnosticStatus.FAIL, DiagnosticStatus.REQUIRED}
        return all(check.status not in blocking for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == DiagnosticStatus.WARNING for check in self.checks)


RuntimeProbe = Callable[[Path], RvcInferenceCapabilities]
ProfileDetector = Callable[[], str]
DiagnosticReporter = Callable[[DiagnosticCheck], None]
DiagnosticStageReporter = Callable[[str, int, int], None]


def run_system_diagnostics(
    paths: AppPaths,
    *,
    runtime_probe: RuntimeProbe | None = None,
    profile_detector: ProfileDetector | None = None,
    reporter: DiagnosticReporter | None = None,
    stage_reporter: DiagnosticStageReporter | None = None,
) -> SystemDiagnostics:
    checks: list[DiagnosticCheck] = []
    total_stages = 6

    def record(check: DiagnosticCheck) -> None:
        checks.append(check)
        if reporter is not None:
            reporter(check)

    def start(key: str, position: int) -> None:
        if stage_reporter is not None:
            stage_reporter(key, position, total_stages)

    runtime_missing_status = (
        DiagnosticStatus.FAIL
        if (paths.runtime_root / RUNTIME_STATE_NAME).is_file()
        else DiagnosticStatus.REQUIRED
    )
    start("storage", 1)
    record(_storage_check(paths))
    start("ffmpeg", 2)
    record(
        _file_pair_check(
            "ffmpeg",
            "FFmpeg",
            paths.runtime_root / "ffmpeg" / "bin",
            missing_status=runtime_missing_status,
        )
    )
    start("demucs", 3)
    record(_demucs_check(paths.runtime_root, missing_status=runtime_missing_status))
    rvc_root = paths.runtime_root / "rvc"
    start("rvc_assets", 4)
    assets = _rvc_assets_check(rvc_root, missing_status=runtime_missing_status)
    record(assets)
    if assets.status in {DiagnosticStatus.FAIL, DiagnosticStatus.REQUIRED}:
        start("ai_runtime", 5)
        record(
            DiagnosticCheck(
                "ai_runtime",
                "Audio Engine",
                assets.status,
                "Install the audio processing components."
                if assets.status == DiagnosticStatus.REQUIRED
                else "The voice conversion runtime is incomplete.",
            )
        )
        start("cuda", 6)
        record(
            DiagnosticCheck(
                "cuda",
                "GPU Acceleration",
                DiagnosticStatus.SKIPPED,
                "Not checked until the audio engine is ready.",
            )
        )
        return SystemDiagnostics(tuple(checks))

    start("ai_runtime", 5)
    capabilities = (runtime_probe or probe_rvc_inference_runtime)(rvc_root)
    if not capabilities.runtime_ready:
        runtime_check, _cuda_check = _runtime_checks(capabilities)
        record(runtime_check)
        start("cuda", 6)
        record(
            DiagnosticCheck(
                "cuda",
                "GPU Acceleration",
                DiagnosticStatus.SKIPPED,
                "Not checked because the audio engine needs repair.",
            )
        )
        return SystemDiagnostics(tuple(checks))

    desired_profile = (profile_detector or detect_rvc_runtime_profile)()
    installed_profile = installed_rvc_runtime_profile(rvc_root)
    profile_error = _profile_error(desired_profile, installed_profile, capabilities)
    fallback_detail = (
        installed_profile.validation_detail
        if installed_profile is not None
        and installed_profile.activation_status == "fallback"
        and installed_profile.preferred_profile == desired_profile
        else ""
    )
    runtime_check, cuda_check = _runtime_checks(
        capabilities,
        profile_error=profile_error,
        fallback_detail=fallback_detail,
    )
    record(runtime_check)
    start("cuda", 6)
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


def _file_pair_check(
    key: str,
    title: str,
    root: Path,
    *,
    missing_status: DiagnosticStatus = DiagnosticStatus.FAIL,
) -> DiagnosticCheck:
    missing = tuple(name for name in ("ffmpeg.exe", "ffprobe.exe") if not (root / name).is_file())
    if missing:
        return DiagnosticCheck(key, title, missing_status, f"Missing: {', '.join(missing)}")
    return DiagnosticCheck(key, title, DiagnosticStatus.PASS, "Bundled tools ready")


def _demucs_check(
    runtime_root: Path,
    *,
    missing_status: DiagnosticStatus = DiagnosticStatus.FAIL,
) -> DiagnosticCheck:
    model = runtime_root / "demucs" / "torch" / "hub" / "checkpoints" / "955717e8-8726e21a.th"
    if not model.is_file():
        return DiagnosticCheck(
            "demucs",
            "Vocal Separation Model",
            missing_status,
            "Separation model is missing.",
        )
    return DiagnosticCheck(
        "demucs",
        "Vocal Separation Model",
        DiagnosticStatus.PASS,
        "Separation model ready",
    )


def _rvc_assets_check(
    rvc_root: Path,
    *,
    missing_status: DiagnosticStatus = DiagnosticStatus.FAIL,
) -> DiagnosticCheck:
    required = (
        Path("infer_cli.py"),
        Path("vc_infer_pipeline.py"),
        *required_rvc_training_paths(),
    )
    missing = tuple(path for path in required if not (rvc_root / path).is_file())
    if missing:
        return DiagnosticCheck(
            "rvc_assets",
            "Voice Conversion Tools",
            missing_status,
            f"Missing: {missing[0].as_posix()}",
        )
    return DiagnosticCheck(
        "rvc_assets",
        "Voice Conversion Tools",
        DiagnosticStatus.PASS,
        "Convert and training assets ready",
    )


def _runtime_checks(
    capabilities: RvcInferenceCapabilities,
    *,
    profile_error: str = "",
    fallback_detail: str = "",
) -> tuple[DiagnosticCheck, DiagnosticCheck]:
    version = f" (Torch {capabilities.torch_version})" if capabilities.torch_version else ""
    runtime = DiagnosticCheck(
        "ai_runtime",
        "Audio Engine",
        DiagnosticStatus.PASS
        if capabilities.runtime_ready and not profile_error
        else DiagnosticStatus.FAIL,
        f"CPU inference and FAISS ready{version}"
        if capabilities.runtime_ready and not profile_error
        else profile_error or capabilities.cpu_detail or "CPU inference or FAISS validation failed.",
    )
    if fallback_detail:
        active = (
            capabilities.directml_device_name
            if capabilities.directml_ready
            else _accelerator_detail(capabilities)
            if capabilities.cuda_ready
            else "CPU fallback active"
        )
        cuda = DiagnosticCheck(
            "cuda",
            "GPU Acceleration",
            DiagnosticStatus.WARNING,
            f"{active} | {_last_detail_line(fallback_detail)}",
        )
    elif capabilities.cuda_ready and capabilities.device_count > 0:
        cuda = DiagnosticCheck(
            "cuda",
            "GPU Acceleration",
            DiagnosticStatus.PASS,
            _accelerator_detail(capabilities),
        )
    elif capabilities.directml_ready:
        cuda = DiagnosticCheck(
            "cuda",
            "GPU Acceleration",
            DiagnosticStatus.PASS,
            capabilities.directml_device_name or "DirectML device ready",
        )
    elif capabilities.cuda_available:
        detail = capabilities.cuda_detail or "CUDA operation failed. CPU conversion will be used."
        cuda = DiagnosticCheck("cuda", "GPU Acceleration", DiagnosticStatus.WARNING, detail)
    elif capabilities.directml_available:
        detail = capabilities.directml_detail or "DirectML operation failed. CPU conversion will be used."
        cuda = DiagnosticCheck("cuda", "GPU Acceleration", DiagnosticStatus.WARNING, detail)
    else:
        cuda = DiagnosticCheck(
            "cuda",
            "GPU Acceleration",
            DiagnosticStatus.WARNING,
            "GPU acceleration is unavailable. CPU conversion and training will be used.",
        )
    return runtime, cuda


def _profile_error(desired_profile, installed_profile, capabilities) -> str:
    installed = installed_profile.profile if installed_profile is not None else ""
    accepted_fallback = bool(
        installed_profile is not None
        and installed_profile.activation_status == "fallback"
        and installed_profile.preferred_profile == desired_profile
    )
    if desired_profile in {
        RVC_PROFILE_CU128,
        RVC_PROFILE_DIRECTML,
        RVC_PROFILE_ROCM_WINDOWS,
    } and installed != desired_profile and not accepted_fallback:
        return (
            f"This GPU requires the RVC {desired_profile} runtime profile. "
            "Install or repair the audio engine."
        )
    if accepted_fallback:
        return ""
    if desired_profile == RVC_PROFILE_CU128 and not capabilities.cuda_ready:
        return capabilities.cuda_detail or "RTX 50-series CUDA validation failed."
    if desired_profile == RVC_PROFILE_DIRECTML and not capabilities.directml_ready:
        return capabilities.directml_detail or "DirectML runtime validation failed."
    if desired_profile == RVC_PROFILE_ROCM_WINDOWS and (
        not capabilities.cuda_ready or not capabilities.hip_version
    ):
        return capabilities.cuda_detail or "AMD ROCm runtime validation failed."
    return ""


def _accelerator_detail(capabilities: RvcInferenceCapabilities) -> str:
    name = capabilities.device_name or f"devices: {capabilities.device_count}"
    return f"ROCm | {name}" if capabilities.hip_version else name


def _last_detail_line(detail: str) -> str:
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    return lines[-1] if lines else "Preferred GPU runtime activation failed."
