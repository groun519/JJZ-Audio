from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jang_app.services.job_diagnostics import classify_error


class RvcTrainingRecoveryAction(StrEnum):
    RETRY = "retry"
    RESUME = "resume"
    RETRY_SAFE_BATCH = "retry_safe_batch"
    OPEN_SYSTEM_SETUP = "open_system_setup"
    RECHECK = "recheck"


@dataclass(frozen=True)
class RvcTrainingRecoveryAdvice:
    diagnostic_code: str
    title: str
    detail: str
    action: RvcTrainingRecoveryAction
    suggested_batch_size: int = 0


_RUNTIME_DIAGNOSTIC_CODES = {
    "RVC_RUNTIME_INCOMPLETE",
    "PYTHON_MODULE_MISSING",
    "RVC_CPU_RUNTIME_INCOMPATIBLE",
    "CUDA_ARCHITECTURE_UNSUPPORTED",
    "CUDA_UNAVAILABLE",
    "DIRECTML_RUNTIME_FAILED",
    "ROCM_RUNTIME_FAILED",
}


def advise_rvc_training_recovery(
    error: str,
    *,
    can_resume: bool,
    current_batch_size: int,
    diagnostic_code: str = "",
) -> RvcTrainingRecoveryAdvice:
    classified = classify_error(error)
    code = diagnostic_code.strip() or classified.code

    if code == "CUDA_OUT_OF_MEMORY":
        current_batch = max(1, int(current_batch_size))
        suggested_batch = max(1, current_batch // 2)
        if suggested_batch < current_batch:
            return RvcTrainingRecoveryAdvice(
                code,
                "GPU memory was exhausted",
                "Retry with batch size {batch}. The checkpoint will be reused when available.",
                RvcTrainingRecoveryAction.RETRY_SAFE_BATCH,
                suggested_batch,
            )
        return RvcTrainingRecoveryAdvice(
            code,
            "GPU memory was exhausted",
            "Close other GPU applications, then retry with batch size 1.",
            (
                RvcTrainingRecoveryAction.RESUME
                if can_resume
                else RvcTrainingRecoveryAction.RETRY
            ),
        )

    if code in _RUNTIME_DIAGNOSTIC_CODES:
        return RvcTrainingRecoveryAdvice(
            code,
            "Training runtime needs attention",
            "Open system setup to repair or change the training runtime, then return and resume.",
            RvcTrainingRecoveryAction.OPEN_SYSTEM_SETUP,
        )

    if code == "STORAGE_INSUFFICIENT":
        return RvcTrainingRecoveryAdvice(
            code,
            "Training storage is insufficient",
            "Free space in the media storage location, then run the preflight check again.",
            RvcTrainingRecoveryAction.RECHECK,
        )

    if code == "RVC_CONSOLE_ENCODING_ERROR":
        return RvcTrainingRecoveryAdvice(
            code,
            "The RVC console could not write the file name",
            "Unicode-safe process output is enabled. Retry the training job.",
            (
                RvcTrainingRecoveryAction.RESUME
                if can_resume
                else RvcTrainingRecoveryAction.RETRY
            ),
        )

    if code == "INVALID_MEDIA_PATH":
        return RvcTrainingRecoveryAdvice(
            code,
            "A training material path is invalid",
            "Review missing or unusually long material paths, then retry.",
            RvcTrainingRecoveryAction.RECHECK,
        )

    return RvcTrainingRecoveryAdvice(
        code,
        "Training stopped before completion",
        (
            "A valid checkpoint was found. Resume from the latest checkpoint."
            if can_resume
            else "No recoverable checkpoint was found. Retry from the prepared materials."
        ),
        (
            RvcTrainingRecoveryAction.RESUME
            if can_resume
            else RvcTrainingRecoveryAction.RETRY
        ),
    )
