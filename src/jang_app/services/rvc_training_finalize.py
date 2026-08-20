from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_logging import get_logger
from jang_app.services.command import CommandResult, run_command
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace
from jang_app.services.rvc_training_index import RvcTrainingIndexResult, load_rvc_training_index
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


class RvcTrainingFinalizeError(RuntimeError):
    """Raised when trained RVC artifacts cannot be validated and registered."""


@dataclass(frozen=True)
class RvcInferenceModelInspection:
    version: str
    sample_rate: int
    f0: bool
    epoch_info: str
    weight_count: int


@dataclass(frozen=True)
class RvcTrainingFinalizeResult:
    record: RvcModelRecord
    inspection: RvcInferenceModelInspection
    index: RvcTrainingIndexResult


def inspect_rvc_inference_model(
    model_path: Path,
    runtime_root: Path,
    *,
    command_runner: Callable[..., CommandResult] = run_command,
) -> RvcInferenceModelInspection:
    model = model_path.expanduser().resolve()
    runtime = runtime_root.expanduser().resolve()
    worker = _artifact_worker_path()
    if not model.is_file() or model.stat().st_size == 0:
        raise RvcTrainingFinalizeError(f"RVC inference model is missing: {model}")
    if not worker.is_file():
        raise RvcTrainingFinalizeError(f"RVC artifact worker is missing: {worker}")
    completed = command_runner(
        [
            str(runtime / "runtime" / "python.exe"),
            str(worker),
            "inspect-model",
            str(model),
        ],
        cwd=runtime,
        env=build_rvc_environment(runtime),
    )
    if completed.returncode != 0:
        raise RvcTrainingFinalizeError(
            f"RVC inference model validation failed with exit code {completed.returncode}: {completed.output}"
        )
    data = _last_json_object(_command_output(completed))
    if (
        data.get("version") != "v2"
        or data.get("sample_rate") != 40000
        or data.get("f0") is not True
        or not isinstance(data.get("weight_count"), int)
        or data["weight_count"] <= 0
    ):
        raise RvcTrainingFinalizeError("RVC inference model does not match the v2/40k/F0 profile.")
    return RvcInferenceModelInspection(
        version="v2",
        sample_rate=40000,
        f0=True,
        epoch_info=str(data.get("epoch_info", "")),
        weight_count=int(data["weight_count"]),
    )


def finalize_rvc_training_artifacts(
    workspace: RvcModelWorkspace,
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    *,
    command_runner: Callable[..., CommandResult] = run_command,
) -> RvcTrainingFinalizeResult:
    state_store = RvcTrainingStateStore(model_id, layout)
    logger = get_logger()
    try:
        state = state_store.refresh_checkpoint_pair()
        if not state.can_resume:
            raise RvcTrainingFinalizeError("A matching G/D checkpoint pair is required.")
        model = layout.weights_dir / f"{layout.rvc_name}.pth"
        inspection = inspect_rvc_inference_model(
            model,
            runtime_root,
            command_runner=command_runner,
        )
        index = load_rvc_training_index(model_id, layout)
        if state.generator_checkpoint is None or state.discriminator_checkpoint is None:
            raise RvcTrainingFinalizeError("A matching G/D checkpoint pair is required.")
        record = workspace.register_training_artifacts(
            model_id,
            inference_model=model,
            index_file=index.added_index,
            generator_checkpoint=state.generator_checkpoint,
            discriminator_checkpoint=state.discriminator_checkpoint,
        )
        state_store.update_phase(RvcTrainingPhase.COMPLETE)
        logger.info("RVC training artifacts registered: model=%s", model_id)
        return RvcTrainingFinalizeResult(record, inspection, index)
    except Exception as exc:
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=str(exc))
        if isinstance(exc, RvcTrainingFinalizeError):
            raise
        raise RvcTrainingFinalizeError(str(exc)) from exc


def _last_json_object(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RvcTrainingFinalizeError("RVC artifact worker did not return a model report.")


def _command_output(result: CommandResult) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _artifact_worker_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rvc_tools" / "rvc_artifact_worker.py"
