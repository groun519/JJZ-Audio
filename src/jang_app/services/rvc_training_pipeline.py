from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from jang_app.services.app_logging import get_logger
from jang_app.services.command import CommandCancellation
from jang_app.services.model_dataset import ModelDataset
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_control import (
    RvcTrainingCancelled,
    raise_if_training_cancelled,
)
from jang_app.services.rvc_training_dataset import RvcTrainingSnapshotStore
from jang_app.services.rvc_training_extract import (
    RvcTrainingExtractError,
    extract_rvc_training_features,
    load_rvc_extract_result,
)
from jang_app.services.rvc_training_filelist import (
    RvcTrainingFilelistError,
    build_rvc_training_filelist,
    load_rvc_training_filelist,
)
from jang_app.services.rvc_training_index import (
    RvcTrainingIndexError,
    RvcTrainingIndexResult,
    build_rvc_training_index,
    load_rvc_training_index,
)
from jang_app.services.rvc_training_preprocess import (
    RvcTrainingPreprocessError,
    load_rvc_preprocess_result,
    preprocess_rvc_training_dataset,
)
from jang_app.services.rvc_training_state import (
    RvcTrainingPhase,
    RvcTrainingState,
    RvcTrainingStateStore,
)
from jang_app.services.rvc_training_spectrogram import (
    RvcTrainingSpectrogramError,
    load_rvc_training_spectrogram_cache,
    prepare_rvc_training_spectrogram_cache,
)
from jang_app.services.rvc_training_train import (
    RvcTrainingRunResult,
    RvcTrainingRunSettings,
    train_rvc_model,
)


class RvcTrainingStage(StrEnum):
    SNAPSHOT = "snapshot"
    PREPROCESS = "preprocess"
    EXTRACT = "extract"
    FILELIST = "filelist"
    SPECTROGRAM = "spectrogram"
    TRAIN = "train"
    INDEX = "index"


@dataclass(frozen=True)
class RvcTrainingPipelineResult:
    state: RvcTrainingState
    dataset_fingerprint: str
    executed_stages: tuple[RvcTrainingStage, ...]
    training: RvcTrainingRunResult | None
    index: RvcTrainingIndexResult | None

    @property
    def stopped(self) -> bool:
        return self.state.phase == RvcTrainingPhase.STOPPED

    @property
    def completed(self) -> bool:
        return self.state.phase == RvcTrainingPhase.COMPLETE


_StageResult = TypeVar("_StageResult")


def run_rvc_training_pipeline(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    dataset: ModelDataset,
    settings: RvcTrainingRunSettings,
    *,
    cancellation: CommandCancellation | None = None,
    progress: Callable[[int], None] | None = None,
    epoch_callback: Callable[[int, int], None] | None = None,
    stage_callback: Callable[[RvcTrainingStage], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> RvcTrainingPipelineResult:
    token = cancellation or CommandCancellation()
    state_store = RvcTrainingStateStore(model_id, layout)
    executed: list[RvcTrainingStage] = []
    fingerprint = ""
    logger = get_logger()
    try:
        _stage(stage_callback, RvcTrainingStage.SNAPSHOT)
        raise_if_training_cancelled(token)
        previous_fingerprint = state_store.load().dataset_fingerprint
        snapshot = RvcTrainingSnapshotStore(model_id, layout).build(
            dataset,
            _scaled_progress(progress, 0, 5),
        )
        fingerprint = snapshot.fingerprint
        if snapshot.fingerprint != previous_fingerprint:
            executed.append(RvcTrainingStage.SNAPSHOT)
        _set_progress(progress, 5)

        _stage(stage_callback, RvcTrainingStage.PREPROCESS)
        _resolve_stage(
            lambda: load_rvc_preprocess_result(model_id, layout),
            lambda: preprocess_rvc_training_dataset(
                model_id,
                layout,
                runtime_root,
                progress=_scaled_progress(progress, 5, 15),
                output_callback=output_callback,
                cancellation=token,
            ),
            RvcTrainingPreprocessError,
            RvcTrainingStage.PREPROCESS,
            executed,
            token,
        )
        _set_progress(progress, 15)

        _stage(stage_callback, RvcTrainingStage.EXTRACT)
        _resolve_stage(
            lambda: load_rvc_extract_result(model_id, layout),
            lambda: extract_rvc_training_features(
                model_id,
                layout,
                runtime_root,
                progress=_scaled_progress(progress, 15, 25),
                output_callback=output_callback,
                cancellation=token,
            ),
            RvcTrainingExtractError,
            RvcTrainingStage.EXTRACT,
            executed,
            token,
        )
        _set_progress(progress, 25)

        _stage(stage_callback, RvcTrainingStage.FILELIST)
        _resolve_stage(
            lambda: load_rvc_training_filelist(model_id, layout),
            lambda: build_rvc_training_filelist(model_id, layout, runtime_root),
            RvcTrainingFilelistError,
            RvcTrainingStage.FILELIST,
            executed,
            token,
        )
        _set_progress(progress, 28)

        _stage(stage_callback, RvcTrainingStage.SPECTROGRAM)
        _resolve_stage(
            lambda: load_rvc_training_spectrogram_cache(model_id, layout),
            lambda: prepare_rvc_training_spectrogram_cache(
                model_id,
                layout,
                runtime_root,
                cancellation=token,
                progress=_scaled_progress(progress, 28, 32),
                output_callback=output_callback,
            ),
            RvcTrainingSpectrogramError,
            RvcTrainingStage.SPECTROGRAM,
            executed,
            token,
        )
        _set_progress(progress, 32)

        _stage(stage_callback, RvcTrainingStage.TRAIN)
        raise_if_training_cancelled(token)
        executed.append(RvcTrainingStage.TRAIN)
        training = train_rvc_model(
            model_id,
            layout,
            runtime_root,
            settings,
            cancellation=token,
            progress=_scaled_progress(progress, 32, 95),
            epoch_callback=epoch_callback,
            output_callback=output_callback,
        )
        if training.stopped:
            return RvcTrainingPipelineResult(
                training.state,
                fingerprint,
                tuple(executed),
                training,
                None,
            )
        _set_progress(progress, 95)

        _stage(stage_callback, RvcTrainingStage.INDEX)
        index = _resolve_stage(
            lambda: load_rvc_training_index(model_id, layout),
            lambda: build_rvc_training_index(
                model_id,
                layout,
                runtime_root,
                cancellation=token,
                progress=_scaled_progress(progress, 95, 100),
                output_callback=output_callback,
            ),
            RvcTrainingIndexError,
            RvcTrainingStage.INDEX,
            executed,
            token,
        )
        complete_state = state_store.update_phase(RvcTrainingPhase.COMPLETE)
        _set_progress(progress, 100)
        return RvcTrainingPipelineResult(
            state=complete_state,
            dataset_fingerprint=fingerprint,
            executed_stages=tuple(executed),
            training=training,
            index=index,
        )
    except RvcTrainingCancelled:
        stopped = state_store.update_phase(RvcTrainingPhase.STOPPED)
        logger.info("RVC training pipeline stopped: model=%s", model_id)
        return RvcTrainingPipelineResult(stopped, fingerprint, tuple(executed), None, None)


def _resolve_stage(
    loader: Callable[[], _StageResult],
    runner: Callable[[], _StageResult],
    recoverable_error: type[Exception],
    stage: RvcTrainingStage,
    executed: list[RvcTrainingStage],
    cancellation: CommandCancellation,
) -> _StageResult:
    raise_if_training_cancelled(cancellation)
    try:
        return loader()
    except recoverable_error:
        raise_if_training_cancelled(cancellation)
        result = runner()
        executed.append(stage)
        return result


def _scaled_progress(
    progress: Callable[[int], None] | None,
    start: int,
    end: int,
) -> Callable[[int], None]:
    def report(value: int) -> None:
        if progress is not None:
            clamped = max(0, min(100, int(value)))
            progress(start + round((end - start) * clamped / 100))

    return report


def _set_progress(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(value)


def _stage(
    callback: Callable[[RvcTrainingStage], None] | None,
    stage: RvcTrainingStage,
) -> None:
    if callback is not None:
        callback(stage)
