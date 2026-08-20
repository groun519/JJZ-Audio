from __future__ import annotations

import re
import shutil
import uuid
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Timer

from jang_app.services.app_logging import get_logger
from jang_app.services.command import (
    CommandCancellation,
    CommandResult,
    run_cancellable_command,
)
from jang_app.services.managed_files import copy_file_atomic, file_sha256, write_json_atomic
from jang_app.services.live_text_file import LiveTextFile
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_script_launcher import (
    prepare_rvc_script_launcher,
    prepare_rvc_script_workspace,
)
from jang_app.services.rvc_training_performance import (
    RvcTrainingDataLoaderSettings,
    conservative_rvc_training_data_loader,
    recommend_rvc_training_data_loader,
)
from jang_app.services.rvc_training_filelist import load_rvc_training_filelist
from jang_app.services.rvc_training_diagnostics import (
    RvcTrainingAttempt,
    RvcTrainingAttemptMonitor,
    RvcTrainingDiagnostics,
)
from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_SAMPLE_RATE,
    RVC_TRAINING_VERSION,
    RvcTrainingRuntimeInspection,
    inspect_rvc_training_runtime,
)
from jang_app.services.rvc_training_state import (
    RvcTrainingPhase,
    RvcTrainingState,
    RvcTrainingStateStore,
)
from jang_app.services.rvc_training_storage import (
    RvcTrainingStorageError,
    prepare_rvc_training_storage,
)


_EPOCH_PATTERN = re.compile(r"====>\s*Epoch:\s*(?P<epoch>\d+)", re.IGNORECASE)
_EPOCH_STEP_PATTERN = re.compile(
    r"Train\s+Epoch:\s*(?P<epoch>\d+)\s*\[\s*(?P<progress>\d+(?:\.\d+)?)%\s*\]",
    re.IGNORECASE,
)
_WEIGHT_SAVE_PATTERN = re.compile(
    r"saving ckpt\s+.+_e(?P<epoch>\d+)_s(?P<step>\d+)",
    re.IGNORECASE,
)
_CHECKPOINT_PATTERN = re.compile(r"^(?P<kind>[GD])_(?P<step>\d+)\.pth$", re.IGNORECASE)
_COMPLETE_MARKER = "training is done"
_FINAL_CHECKPOINT_MARKER = "saving final ckpt:success"
_TRAINER_EXIT_GRACE_SECONDS = 10.0
_DATA_LOADER_FAILURE_MARKERS = (
    "dataloader worker",
    "data loader worker",
    "brokenpipeerror",
    "can't pickle",
    "cannot pickle",
    "paging file is too small",
    "dataloader timed out",
    "data loader timed out",
)
_NATIVE_RUNTIME_CRASH_MARKERS = (
    "windows fatal exception: access violation",
    "0xc0000005",
    "3221225477",
    "rtluserthreadstart",
)


class RvcTrainingRunError(RuntimeError):
    """Raised when the RVC trainer cannot start or produce a valid result."""


class _TrainingProcessCompletionGuard:
    """Stop a trainer that remains alive after its final checkpoint is durable."""

    def __init__(
        self,
        cancellation: CommandCancellation,
        *,
        grace_seconds: float = _TRAINER_EXIT_GRACE_SECONDS,
    ) -> None:
        self._cancellation = cancellation
        self._grace_seconds = max(0.1, float(grace_seconds))
        self._lock = RLock()
        self._timer: Timer | None = None
        self._closed = False
        self._forced = False

    @property
    def forced(self) -> bool:
        with self._lock:
            return self._forced

    def observe(self, line: str) -> None:
        if _FINAL_CHECKPOINT_MARKER not in str(line).casefold():
            return
        with self._lock:
            if self._closed or self._timer is not None:
                return
            timer = Timer(self._grace_seconds, self._force_stop)
            timer.daemon = True
            self._timer = timer
        timer.start()

    def cancel(self) -> None:
        with self._lock:
            self._closed = True
            timer = self._timer
        if timer is not None:
            timer.cancel()

    def _force_stop(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._forced = True
        get_logger().warning(
            "RVC trainer remained alive %.1f seconds after the final checkpoint; "
            "terminating the completed process tree",
            self._grace_seconds,
        )
        self._cancellation.terminate_current()


@dataclass(frozen=True)
class RvcTrainingRunSettings:
    target_epoch: int = 20
    batch_size: int = 4
    save_every_epoch: int = 5
    gpu_index: int = 0
    cache_in_gpu: bool = False
    resume: bool = True

    def validate(self) -> None:
        if self.target_epoch <= 0:
            raise RvcTrainingRunError("Target epoch must be greater than zero.")
        if self.batch_size <= 0 or self.batch_size > 64:
            raise RvcTrainingRunError("Batch size must be between 1 and 64.")
        if self.save_every_epoch <= 0 or self.save_every_epoch > self.target_epoch:
            raise RvcTrainingRunError("Checkpoint interval must fit inside the target epoch.")
        if self.gpu_index < 0:
            raise RvcTrainingRunError("GPU index cannot be negative.")


@dataclass(frozen=True)
class RvcTrainingRunResult:
    state: RvcTrainingState
    inference_model: Path | None
    log_path: Path
    resumed: bool
    stopped: bool

    @property
    def completed(self) -> bool:
        return self.state.phase == RvcTrainingPhase.COMPLETE


TrainingCommandRunner = Callable[..., CommandResult]


def train_rvc_model(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    settings: RvcTrainingRunSettings,
    *,
    cancellation: CommandCancellation | None = None,
    progress: Callable[[int], None] | None = None,
    epoch_callback: Callable[[int, int], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
    runtime_callback: Callable[[RvcTrainingRuntimeInspection], None] | None = None,
    command_runner: TrainingCommandRunner = run_cancellable_command,
    runtime_inspector: Callable[..., RvcTrainingRuntimeInspection] = inspect_rvc_training_runtime,
) -> RvcTrainingRunResult:
    settings.validate()
    runtime = runtime_root.expanduser().resolve()
    inspection = runtime_inspector(runtime, check_cuda=True)
    if runtime_callback is not None:
        runtime_callback(inspection)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingRunError(f"RVC training runtime is incomplete: {missing}")
    if not inspection.ready:
        raise RvcTrainingRunError(
            inspection.cuda_error or "The RVC runtime cannot train a model on this PC."
        )
    if inspection.training_accelerated and settings.gpu_index >= inspection.cuda_device_count:
        raise RvcTrainingRunError("The selected GPU is not available for RVC training.")

    load_rvc_training_filelist(model_id, layout)
    layout.create()
    try:
        storage = prepare_rvc_training_storage(layout)
    except RvcTrainingStorageError as exc:
        raise RvcTrainingRunError(str(exc)) from exc
    _prepare_package_config(runtime, layout, use_half=inspection.training_accelerated)
    prepare_rvc_script_workspace(layout.root, runtime)
    data_loader_settings = recommend_rvc_training_data_loader(
        inspection,
        windowless_workers_available=(runtime / "runtime" / "pythonw.exe").is_file(),
    )
    training_diagnostics = RvcTrainingDiagnostics.for_current_task(model_id)
    if training_diagnostics is not None:
        training_diagnostics.record_runtime(
            {
                "runtime_root": runtime,
                "backend": inspection.backend.value,
                "torch_version": inspection.torch_version,
                "cuda_version": inspection.cuda_version,
                "hip_version": inspection.hip_version,
                "cuda_available": inspection.cuda_available,
                "cuda_device_count": inspection.cuda_device_count,
                "device_capability": inspection.device_capability,
                "training_accelerated": inspection.training_accelerated,
            }
        )
    active_attempt = _begin_training_attempt(
        training_diagnostics,
        settings,
        data_loader_settings,
        reason="initial",
    )
    launcher = prepare_rvc_script_launcher(
        layout.root / ".jjzero" / "train_rvc.py",
        runtime,
        runtime / "train_nsf_sim_cache_sid_load_pretrain.py",
        atomic_torch_saves=True,
        compact_rvc_checkpoints=True,
        data_loader_settings=data_loader_settings,
        rocm_single_process_training=True,
        legacy_i18n=True,
        diagnostic_directory=active_attempt.folder if active_attempt else None,
        diagnostic_attempt_id=active_attempt.attempt_id if active_attempt else "",
    )
    state_store = RvcTrainingStateStore(model_id, layout)
    _keep_latest_checkpoint_pair(layout)
    state = state_store.refresh_checkpoint_pair()
    if settings.resume and state.current_epoch > 0 and not state.can_resume:
        state = state_store.reset_for_new_training()
    resumed = settings.resume and state.can_resume
    if not settings.resume:
        _archive_checkpoints(layout)
        state = state_store.reset_for_new_training()
    if settings.target_epoch <= state.current_epoch:
        raise RvcTrainingRunError("Target epoch must be greater than the current epoch.")

    final_model = layout.weights_dir / f"{layout.rvc_name}.pth"
    backup = _backup_final_model(final_model, layout)
    log_path = layout.experiment_dir / "train.log"
    log_offset = log_path.stat().st_size if log_path.is_file() else 0
    token = cancellation or CommandCancellation()
    completion_guard = _TrainingProcessCompletionGuard(token)
    try:
        state_store.begin_training(settings.target_epoch)
    except Exception:
        _discard_backup(backup, layout)
        raise
    _report(progress, epoch_callback, state.current_epoch, settings.target_epoch)
    logger = get_logger()
    logger.info(
        "Starting RVC training: model=%s target_epoch=%s resumed=%s backend=%s "
        "accelerated=%s data_workers=%s pin_memory=%s free_space_gib=%.1f",
        model_id,
        settings.target_epoch,
        resumed,
        inspection.backend.value,
        inspection.training_accelerated,
        data_loader_settings.workers,
        data_loader_settings.pin_memory,
        storage.available_bytes / 1024**3,
    )

    output_lock = RLock()
    recent_output: deque[str] = deque()
    recent_output_set: set[str] = set()
    active_monitor: RvcTrainingAttemptMonitor | None = None
    attempt_log_offset = log_offset
    last_returncode: int | None = None
    resume_load_error = ""
    safe_retry_requested = False

    def handle_output(line: str) -> None:
        nonlocal resume_load_error, safe_retry_requested
        text = line.strip()
        if not text:
            return
        completion_guard.observe(text)
        if active_monitor is not None:
            active_monitor.observe_output(text)
        with output_lock:
            if text in recent_output_set:
                return
            recent_output.append(text)
            recent_output_set.add(text)
            if len(recent_output) > 2048:
                recent_output_set.discard(recent_output.popleft())
            if resumed and text.startswith("JJZERO_CHECKPOINT_LOAD_FAILED"):
                resume_load_error = text
                token.request_cancel()
            if text.startswith("JJZERO_DATA_LOADER_WORKER_EXITED"):
                safe_retry_requested = True
                token.terminate_current()
            step_match = _EPOCH_STEP_PATTERN.search(text)
            if step_match is not None:
                _report_epoch_step(
                    progress,
                    int(step_match.group("epoch")),
                    float(step_match.group("progress")),
                    settings.target_epoch,
                )
            match = _EPOCH_PATTERN.search(text)
            if match is not None:
                epoch = min(settings.target_epoch, int(match.group("epoch")))
                state_store.record_epoch(epoch)
                _report(progress, epoch_callback, epoch, settings.target_epoch)
            save_match = _WEIGHT_SAVE_PATTERN.search(text)
            if save_match is not None:
                epoch = min(settings.target_epoch, int(save_match.group("epoch")))
                state_store.record_epoch(epoch)
                _keep_latest_checkpoint_pair(layout, int(save_match.group("step")))
                state_store.refresh_checkpoint_pair()
                _report(progress, epoch_callback, epoch, settings.target_epoch)
            if output_callback is not None:
                output_callback(text)

    try:
        if output_callback is not None:
            output_callback(
                "JJZERO_TRAINING_START "
                f"current={state.current_epoch} target={settings.target_epoch}"
            )
        command = _training_command(
            runtime,
            layout,
            settings,
            launcher,
            accelerated=inspection.training_accelerated,
        )
        with LiveTextFile(log_path, log_offset, handle_output):
            active_monitor = RvcTrainingAttemptMonitor(
                training_diagnostics,
                active_attempt,
                activity_callback=handle_output,
            )
            active_monitor.start()
            attempt_log_offset = log_path.stat().st_size if log_path.is_file() else 0
            result = command_runner(
                command,
                cwd=layout.root,
                env=build_rvc_environment(runtime),
                output_callback=handle_output,
                cancellation=token,
            )
            completion_guard.cancel()
            last_returncode = result.returncode
            active_monitor.stop()
            active_monitor = None
            if training_diagnostics is not None and active_attempt is not None:
                training_diagnostics.capture_train_log(
                    active_attempt,
                    log_path,
                    attempt_log_offset,
                )
            loader_diagnostics = (
                f"returncode={result.returncode} "
                f"windows_status=0x{result.returncode & 0xFFFFFFFF:08X}\n"
                f"{result.output}\n{_log_delta(log_path, attempt_log_offset)}"
            )
            if (
                data_loader_settings.workers > 0
                and not result.cancelled
                and not token.is_requested
                and (
                    safe_retry_requested
                    or _is_data_loader_failure(loader_diagnostics)
                    or _is_native_runtime_crash(loader_diagnostics)
                )
            ):
                logger.warning(
                    "RVC training process failed with parallel data loading; "
                    "retrying safely: model=%s workers=%s native_crash=%s",
                    model_id,
                    data_loader_settings.workers,
                    _is_native_runtime_crash(loader_diagnostics),
                )
                handle_output("JJZERO_DATA_LOADER_FALLBACK workers=0")
                if training_diagnostics is not None and active_attempt is not None:
                    diagnostic_code = training_diagnostics.diagnose_attempt(
                        active_attempt,
                        loader_diagnostics,
                    )
                    training_diagnostics.finish_attempt(
                        active_attempt,
                        status="failed",
                        returncode=result.returncode,
                        diagnostic_code=diagnostic_code,
                        detail="Parallel data loading failed; retrying safely.",
                    )
                fallback_loader = conservative_rvc_training_data_loader()
                active_attempt = _begin_training_attempt(
                    training_diagnostics,
                    settings,
                    fallback_loader,
                    reason="safe_fallback",
                )
                prepare_rvc_script_launcher(
                    launcher,
                    runtime,
                    runtime / "train_nsf_sim_cache_sid_load_pretrain.py",
                    atomic_torch_saves=True,
                    compact_rvc_checkpoints=True,
                    data_loader_settings=fallback_loader,
                    rocm_single_process_training=True,
                    legacy_i18n=True,
                    diagnostic_directory=(
                        active_attempt.folder if active_attempt else None
                    ),
                    diagnostic_attempt_id=(
                        active_attempt.attempt_id if active_attempt else ""
                    ),
                )
                active_monitor = RvcTrainingAttemptMonitor(
                    training_diagnostics,
                    active_attempt,
                    activity_callback=handle_output,
                )
                active_monitor.start()
                completion_guard = _TrainingProcessCompletionGuard(token)
                attempt_log_offset = (
                    log_path.stat().st_size if log_path.is_file() else 0
                )
                result = command_runner(
                    command,
                    cwd=layout.root,
                    env=build_rvc_environment(runtime),
                    output_callback=handle_output,
                    cancellation=token,
                )
                completion_guard.cancel()
                last_returncode = result.returncode
                active_monitor.stop()
                active_monitor = None
                if training_diagnostics is not None and active_attempt is not None:
                    training_diagnostics.capture_train_log(
                        active_attempt,
                        log_path,
                        attempt_log_offset,
                    )
        refreshed = state_store.refresh_checkpoint_pair()
        if resume_load_error:
            raise RvcTrainingRunError(
                "RVC could not restore the saved training checkpoint: "
                f"{resume_load_error}"
            )
        if result.cancelled or token.is_requested:
            if training_diagnostics is not None and active_attempt is not None:
                training_diagnostics.finish_attempt(
                    active_attempt,
                    status="cancelled",
                    returncode=result.returncode,
                    detail="Training was stopped by the user.",
                )
            _restore_final_model(final_model, backup, layout)
            stopped = state_store.update_phase(RvcTrainingPhase.STOPPED)
            logger.info("RVC training stopped: model=%s", model_id)
            return RvcTrainingRunResult(stopped, _existing(final_model), log_path, resumed, True)

        output = f"{result.output}\n{_log_delta(log_path, log_offset)}".casefold()
        if (
            _COMPLETE_MARKER not in output
            or not final_model.is_file()
            or final_model.stat().st_size == 0
            or not refreshed.can_resume
            or _model_is_unchanged(final_model, backup)
        ):
            detail = result.output or f"trainer exited with code {result.returncode}"
            raise RvcTrainingRunError(f"RVC training did not produce a complete model: {detail}")
        state_store.record_epoch(settings.target_epoch)
        completed = state_store.update_phase(RvcTrainingPhase.COMPLETE)
        if training_diagnostics is not None and active_attempt is not None:
            training_diagnostics.finish_attempt(
                active_attempt,
                status="completed",
                returncode=result.returncode,
            )
        _discard_backup(backup, layout)
        _report(
            progress,
            epoch_callback,
            settings.target_epoch,
            settings.target_epoch,
        )
        logger.info("RVC training complete: model=%s output=%s", model_id, final_model)
        return RvcTrainingRunResult(completed, final_model, log_path, resumed, False)
    except Exception as exc:
        completion_guard.cancel()
        if active_monitor is not None:
            active_monitor.stop()
            active_monitor = None
        diagnostic_code = ""
        if training_diagnostics is not None and active_attempt is not None:
            training_diagnostics.capture_train_log(
                active_attempt,
                log_path,
                attempt_log_offset,
            )
            diagnostic_code = training_diagnostics.diagnose_attempt(
                active_attempt,
                str(exc),
            )
            training_diagnostics.finish_attempt(
                active_attempt,
                status="failed",
                returncode=last_returncode,
                diagnostic_code=diagnostic_code,
                detail=str(exc),
            )
        error_detail = str(exc)
        if diagnostic_code and "JJZERO_DIAGNOSTIC_CODE=" not in error_detail:
            error_detail = f"JJZERO_DIAGNOSTIC_CODE={diagnostic_code}\n{error_detail}"
        _restore_final_model(final_model, backup, layout)
        state_store.refresh_checkpoint_pair()
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=error_detail)
        logger.error("RVC training failed: model=%s error=%s", model_id, error_detail)
        if isinstance(exc, RvcTrainingRunError) and error_detail == str(exc):
            raise
        raise RvcTrainingRunError(error_detail) from exc


def _begin_training_attempt(
    diagnostics: RvcTrainingDiagnostics | None,
    settings: RvcTrainingRunSettings,
    loader: RvcTrainingDataLoaderSettings,
    *,
    reason: str,
) -> RvcTrainingAttempt | None:
    if diagnostics is None:
        return None
    return diagnostics.begin_attempt(
        {
            "reason": reason,
            "target_epoch": settings.target_epoch,
            "batch_size": settings.batch_size,
            "save_every_epoch": settings.save_every_epoch,
            "gpu_index": settings.gpu_index,
            "cache_in_gpu": settings.cache_in_gpu,
            "resume": settings.resume,
            "data_loader_workers": loader.workers,
            "data_loader_prefetch": loader.prefetch_factor,
            "data_loader_pin_memory": loader.pin_memory,
            "data_loader_persistent": loader.persistent_workers,
            "data_loader_timeout_seconds": loader.timeout_seconds,
        }
    )


def _training_command(
    runtime: Path,
    layout: RvcModelPackageLayout,
    settings: RvcTrainingRunSettings,
    launcher: Path,
    *,
    accelerated: bool = True,
) -> list[str]:
    return [
        str(runtime / "runtime" / "python.exe"),
        str(launcher),
        "-e",
        layout.rvc_name,
        "-sr",
        "40k",
        "-f0",
        "1",
        "-bs",
        str(settings.batch_size),
        "-g",
        str(settings.gpu_index),
        "-te",
        str(settings.target_epoch),
        "-se",
        str(settings.save_every_epoch),
        "-pg",
        str(runtime / "pretrained_v2" / "f0G40k.pth"),
        "-pd",
        str(runtime / "pretrained_v2" / "f0D40k.pth"),
        "-l",
        "0",
        "-c",
        "1" if settings.cache_in_gpu and accelerated else "0",
        "-sw",
        "1",
        "-v",
        RVC_TRAINING_VERSION,
    ]


def _is_data_loader_failure(output: str) -> bool:
    lowered = str(output).casefold()
    return any(marker in lowered for marker in _DATA_LOADER_FAILURE_MARKERS)


def _is_native_runtime_crash(output: str) -> bool:
    lowered = str(output).casefold()
    return any(marker in lowered for marker in _NATIVE_RUNTIME_CRASH_MARKERS)


def _prepare_package_config(
    runtime: Path,
    layout: RvcModelPackageLayout,
    *,
    use_half: bool,
) -> None:
    source = runtime / "configs" / "40k.json"
    if not source.is_file():
        raise RvcTrainingRunError(f"RVC training config is missing: {source}")
    target = layout.root / "configs" / "40k.json"
    if use_half:
        copy_file_atomic(source, target)
        return
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        data["train"]["fp16_run"] = False
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RvcTrainingRunError(f"RVC training config is invalid: {source}") from exc
    write_json_atomic(target, data)


def _archive_checkpoints(layout: RvcModelPackageLayout) -> Path | None:
    checkpoints = tuple(
        sorted(
            (*layout.experiment_dir.glob("G_*.pth"), *layout.experiment_dir.glob("D_*.pth")),
            key=lambda path: path.name.casefold(),
        )
    )
    if not checkpoints:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = layout.model_dir / "training" / "history" / f"{stamp}-{uuid.uuid4().hex[:8]}"
    moved: list[Path] = []
    try:
        archive.mkdir(parents=True, exist_ok=False)
        for checkpoint in checkpoints:
            target = archive / checkpoint.name
            shutil.move(str(checkpoint), str(target))
            moved.append(target)
    except Exception:
        for target in reversed(moved):
            shutil.move(str(target), str(layout.experiment_dir / target.name))
        if archive.is_dir() and not tuple(archive.iterdir()):
            archive.rmdir()
        raise
    return archive


def _keep_latest_checkpoint_pair(
    layout: RvcModelPackageLayout,
    preferred_step: int | None = None,
) -> None:
    generators: dict[int, Path] = {}
    discriminators: dict[int, Path] = {}
    for path in layout.experiment_dir.glob("*.pth"):
        match = _CHECKPOINT_PATTERN.fullmatch(path.name) if path.is_file() else None
        if match is None:
            continue
        target = generators if match.group("kind").casefold() == "g" else discriminators
        target[int(match.group("step"))] = path
    shared_steps = generators.keys() & discriminators.keys()
    keep_step = (
        preferred_step
        if preferred_step is not None and preferred_step in shared_steps
        else max(shared_steps) if shared_steps else None
    )
    for step, path in (*generators.items(), *discriminators.items()):
        if step != keep_step:
            path.unlink(missing_ok=True)


def _backup_final_model(final_model: Path, layout: RvcModelPackageLayout) -> Path | None:
    if not final_model.is_file():
        return None
    backup = layout.model_dir / "training" / "run-backups" / uuid.uuid4().hex / final_model.name
    copy_file_atomic(final_model, backup)
    return backup


def _restore_final_model(
    final_model: Path,
    backup: Path | None,
    layout: RvcModelPackageLayout,
) -> None:
    if backup is not None and backup.is_file():
        copy_file_atomic(backup, final_model)
        _discard_backup(backup, layout)
        return
    if final_model.is_file() and _is_within(final_model, layout.weights_dir):
        final_model.unlink()


def _discard_backup(backup: Path | None, layout: RvcModelPackageLayout) -> None:
    if backup is None:
        return
    root = layout.model_dir / "training" / "run-backups"
    directory = backup.parent
    if directory.is_dir() and _is_within(directory, root):
        shutil.rmtree(directory)


def _model_is_unchanged(final_model: Path, backup: Path | None) -> bool:
    return (
        backup is not None
        and backup.is_file()
        and final_model.is_file()
        and file_sha256(final_model) == file_sha256(backup)
    )


def _log_delta(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as source:
        if path.stat().st_size >= offset:
            source.seek(offset)
        return source.read().decode("utf-8", errors="replace")


def _report(
    progress: Callable[[int], None] | None,
    epoch_callback: Callable[[int, int], None] | None,
    epoch: int,
    target: int,
) -> None:
    if progress is not None:
        progress(max(0, min(100, round(epoch * 100 / target))))
    if epoch_callback is not None:
        epoch_callback(epoch, target)


def _report_epoch_step(
    progress: Callable[[int], None] | None,
    epoch: int,
    epoch_progress: float,
    target: int,
) -> None:
    if progress is None or target <= 0:
        return
    completed_epochs = max(0.0, float(epoch - 1))
    current_fraction = max(0.0, min(100.0, epoch_progress)) / 100.0
    overall = 100.0 * min(float(target), completed_epochs + current_fraction) / target
    progress(max(0, min(100, round(overall))))


def _existing(path: Path) -> Path | None:
    return path if path.is_file() else None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
