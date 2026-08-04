from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_F0_METHOD,
    RVC_TRAINING_SAMPLE_RATE,
    RVC_TRAINING_VERSION,
)


TRAINING_STATE_VERSION = 1
TRAINING_STATE_FILE_NAME = "training.json"
DEFAULT_TARGET_EPOCH = 20
_CHECKPOINT_PATTERN = re.compile(r"^(?P<kind>[GD])_(?P<step>\d+)\.pth$", re.IGNORECASE)
_DATASET_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class RvcTrainingStateError(RuntimeError):
    """Raised when a managed model training state is invalid or unreadable."""


class RvcTrainingPhase(StrEnum):
    IDLE = "idle"
    PREPROCESS = "preprocess"
    PREPROCESSED = "preprocessed"
    EXTRACT = "extract"
    FEATURES_READY = "features_ready"
    FILELIST_READY = "filelist_ready"
    TRAIN = "train"
    STOPPED = "stopped"
    INDEX = "index"
    INDEX_READY = "index_ready"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class RvcTrainingSettings:
    version: str = RVC_TRAINING_VERSION
    sample_rate: int = RVC_TRAINING_SAMPLE_RATE
    f0_method: str = RVC_TRAINING_F0_METHOD
    speaker_id: int = 0

    def validate(self) -> None:
        if (
            self.version != RVC_TRAINING_VERSION
            or self.sample_rate != RVC_TRAINING_SAMPLE_RATE
            or self.f0_method != RVC_TRAINING_F0_METHOD
            or self.speaker_id != 0
        ):
            raise RvcTrainingStateError("Only the RVC v2 40k RMVPE single-speaker profile is supported.")


@dataclass(frozen=True)
class RvcTrainingState:
    model_id: str
    settings: RvcTrainingSettings
    phase: RvcTrainingPhase
    dataset_fingerprint: str
    current_epoch: int
    target_epoch: int
    checkpoint_step: int
    generator_checkpoint: Path | None
    discriminator_checkpoint: Path | None
    created_at: str
    updated_at: str
    last_error: str = ""

    @property
    def can_resume(self) -> bool:
        return (
            self.checkpoint_step > 0
            and self.generator_checkpoint is not None
            and self.generator_checkpoint.is_file()
            and self.discriminator_checkpoint is not None
            and self.discriminator_checkpoint.is_file()
        )


class RvcTrainingStateStore:
    def __init__(self, model_id: str, layout: RvcModelPackageLayout) -> None:
        if not model_id or any(character in model_id for character in "\\/:"):
            raise RvcTrainingStateError(f"Invalid model id: {model_id}")
        self.model_id = model_id
        self.layout = layout
        self.path = layout.model_dir / TRAINING_STATE_FILE_NAME

    def load(self) -> RvcTrainingState:
        if not self.path.is_file():
            return self._new_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return self._state_from_data(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RvcTrainingStateError(f"Training state cannot be read: {self.path}") from exc

    def initialize(self) -> RvcTrainingState:
        state = self.load()
        if not self.path.is_file():
            return self.save(state)
        return state

    def save(self, state: RvcTrainingState) -> RvcTrainingState:
        self._validate(state)
        updated = replace(state, updated_at=_now())
        write_json_atomic(self.path, self._state_to_data(updated))
        return updated

    def refresh_checkpoint_pair(self) -> RvcTrainingState:
        state = self.load()
        generator, discriminator, step = _latest_checkpoint_pair(self.layout.experiment_dir)
        refreshed = replace(
            state,
            checkpoint_step=step,
            generator_checkpoint=generator,
            discriminator_checkpoint=discriminator,
        )
        return self.save(refreshed) if refreshed != state or not self.path.is_file() else state

    def update_dataset_fingerprint(self, fingerprint: str) -> RvcTrainingState:
        if not _DATASET_FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise RvcTrainingStateError("Dataset fingerprint is invalid.")
        state = self.load()
        if state.dataset_fingerprint == fingerprint:
            return state
        return self.save(
            replace(
                state,
                phase=RvcTrainingPhase.IDLE,
                dataset_fingerprint=fingerprint,
                last_error="",
            )
        )

    def update_phase(
        self,
        phase: RvcTrainingPhase,
        *,
        last_error: str = "",
    ) -> RvcTrainingState:
        state = self.load()
        return self.save(replace(state, phase=phase, last_error=last_error.strip()[:4000]))

    def begin_training(self, target_epoch: int) -> RvcTrainingState:
        state = self.load()
        if target_epoch <= state.current_epoch:
            raise RvcTrainingStateError("Target epoch must be greater than the current epoch.")
        return self.save(
            replace(
                state,
                phase=RvcTrainingPhase.TRAIN,
                target_epoch=target_epoch,
                last_error="",
            )
        )

    def record_epoch(self, current_epoch: int) -> RvcTrainingState:
        state = self.load()
        epoch = max(state.current_epoch, int(current_epoch))
        if epoch > state.target_epoch:
            raise RvcTrainingStateError("Current epoch cannot exceed the target epoch.")
        return self.save(replace(state, current_epoch=epoch))

    def reset_for_new_training(self) -> RvcTrainingState:
        state = self.load()
        return self.save(
            replace(
                state,
                phase=RvcTrainingPhase.FILELIST_READY,
                current_epoch=0,
                checkpoint_step=0,
                generator_checkpoint=None,
                discriminator_checkpoint=None,
                last_error="",
            )
        )

    def recover_interrupted(self) -> RvcTrainingState:
        state = self.load()
        active_phases = {
            RvcTrainingPhase.PREPROCESS,
            RvcTrainingPhase.EXTRACT,
            RvcTrainingPhase.TRAIN,
        }
        if state.phase not in active_phases:
            return state
        self.refresh_checkpoint_pair()
        return self.update_phase(RvcTrainingPhase.STOPPED)

    def _new_state(self) -> RvcTrainingState:
        now = _now()
        return RvcTrainingState(
            model_id=self.model_id,
            settings=RvcTrainingSettings(),
            phase=RvcTrainingPhase.IDLE,
            dataset_fingerprint="",
            current_epoch=0,
            target_epoch=DEFAULT_TARGET_EPOCH,
            checkpoint_step=0,
            generator_checkpoint=None,
            discriminator_checkpoint=None,
            created_at=now,
            updated_at=now,
        )

    def _validate(self, state: RvcTrainingState) -> None:
        if state.model_id != self.model_id:
            raise RvcTrainingStateError("Training state belongs to a different model.")
        state.settings.validate()
        if state.dataset_fingerprint and not _DATASET_FINGERPRINT_PATTERN.fullmatch(
            state.dataset_fingerprint
        ):
            raise RvcTrainingStateError("Dataset fingerprint is invalid.")
        if (
            state.current_epoch < 0
            or state.target_epoch <= 0
            or state.current_epoch > state.target_epoch
        ):
            raise RvcTrainingStateError("Training epoch values are invalid.")
        if state.checkpoint_step < 0:
            raise RvcTrainingStateError("Checkpoint step cannot be negative.")
        checkpoints = (state.generator_checkpoint, state.discriminator_checkpoint)
        if (checkpoints[0] is None) != (checkpoints[1] is None):
            raise RvcTrainingStateError("Generator and discriminator checkpoints must be stored as a pair.")
        has_checkpoint_pair = checkpoints[0] is not None
        if has_checkpoint_pair != (state.checkpoint_step > 0):
            raise RvcTrainingStateError("Checkpoint paths and step must be stored together.")
        for checkpoint in checkpoints:
            if checkpoint is not None and not _is_within(checkpoint, self.layout.experiment_dir):
                raise RvcTrainingStateError("Training checkpoints must remain inside the model package.")
        if has_checkpoint_pair:
            generator_step = _checkpoint_step(checkpoints[0], "G")
            discriminator_step = _checkpoint_step(checkpoints[1], "D")
            if generator_step != state.checkpoint_step or discriminator_step != state.checkpoint_step:
                raise RvcTrainingStateError("Checkpoint filenames do not match the stored step.")

    def _state_to_data(self, state: RvcTrainingState) -> dict[str, object]:
        return {
            "version": TRAINING_STATE_VERSION,
            "model_id": state.model_id,
            "settings": {
                "version": state.settings.version,
                "sample_rate": state.settings.sample_rate,
                "f0_method": state.settings.f0_method,
                "speaker_id": state.settings.speaker_id,
            },
            "phase": state.phase.value,
            "dataset_fingerprint": state.dataset_fingerprint,
            "current_epoch": state.current_epoch,
            "target_epoch": state.target_epoch,
            "checkpoint": {
                "step": state.checkpoint_step,
                "generator": self._relative_path(state.generator_checkpoint),
                "discriminator": self._relative_path(state.discriminator_checkpoint),
            },
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "last_error": state.last_error,
        }

    def _state_from_data(self, data: object) -> RvcTrainingState:
        if not isinstance(data, dict) or data.get("version") != TRAINING_STATE_VERSION:
            raise RvcTrainingStateError("Training state version is not supported.")
        if data.get("model_id") != self.model_id:
            raise RvcTrainingStateError("Training state belongs to a different model.")
        raw_settings = data["settings"]
        raw_checkpoint = data["checkpoint"]
        if not isinstance(raw_settings, dict) or not isinstance(raw_checkpoint, dict):
            raise RvcTrainingStateError("Training state sections are invalid.")
        state = RvcTrainingState(
            model_id=self.model_id,
            settings=RvcTrainingSettings(
                version=str(raw_settings["version"]),
                sample_rate=int(raw_settings["sample_rate"]),
                f0_method=str(raw_settings["f0_method"]),
                speaker_id=int(raw_settings["speaker_id"]),
            ),
            phase=RvcTrainingPhase(str(data["phase"])),
            dataset_fingerprint=str(data.get("dataset_fingerprint", "")),
            current_epoch=int(data["current_epoch"]),
            target_epoch=int(data["target_epoch"]),
            checkpoint_step=int(raw_checkpoint.get("step", 0)),
            generator_checkpoint=self._manifest_path(raw_checkpoint.get("generator")),
            discriminator_checkpoint=self._manifest_path(raw_checkpoint.get("discriminator")),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            last_error=str(data.get("last_error", "")),
        )
        self._validate(state)
        return state

    def _relative_path(self, path: Path | None) -> str:
        if path is None:
            return ""
        return path.expanduser().resolve().relative_to(self.layout.model_dir.resolve()).as_posix()

    def _manifest_path(self, value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        resolved = (self.layout.model_dir / Path(value)).resolve()
        if not _is_within(resolved, self.layout.model_dir):
            raise RvcTrainingStateError("Training state path leaves the model package.")
        return resolved


def _latest_checkpoint_pair(experiment_dir: Path) -> tuple[Path | None, Path | None, int]:
    generators: dict[int, Path] = {}
    discriminators: dict[int, Path] = {}
    if experiment_dir.is_dir():
        for path in experiment_dir.iterdir():
            match = _CHECKPOINT_PATTERN.fullmatch(path.name) if path.is_file() else None
            if match is None:
                continue
            step = int(match.group("step"))
            target = generators if match.group("kind").casefold() == "g" else discriminators
            target[step] = path.resolve()
    shared_steps = generators.keys() & discriminators.keys()
    if not shared_steps:
        return None, None, 0
    step = max(shared_steps)
    return generators[step], discriminators[step], step


def _checkpoint_step(path: Path | None, expected_kind: str) -> int:
    match = _CHECKPOINT_PATTERN.fullmatch(path.name) if path is not None else None
    if match is None or match.group("kind").casefold() != expected_kind.casefold():
        return -1
    return int(match.group("step"))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(UTC).isoformat()
