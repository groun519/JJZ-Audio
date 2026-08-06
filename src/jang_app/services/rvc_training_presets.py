from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RvcTrainingPresetId(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    HIGH_QUALITY = "high_quality"
    CUSTOM = "custom"


@dataclass(frozen=True)
class RvcTrainingPreset:
    preset_id: RvcTrainingPresetId
    label: str
    purpose: str
    epoch_increment: int
    checkpoint_interval: int


@dataclass(frozen=True)
class RvcTrainingRecommendation:
    preset: RvcTrainingPreset
    target_epoch: int
    batch_size: int
    checkpoint_interval: int


TRAINING_PRESETS = {
    RvcTrainingPresetId.QUICK: RvcTrainingPreset(
        RvcTrainingPresetId.QUICK,
        "Quick Check",
        "Quick pipeline validation",
        20,
        5,
    ),
    RvcTrainingPresetId.STANDARD: RvcTrainingPreset(
        RvcTrainingPresetId.STANDARD,
        "Standard",
        "Balanced training for general model creation",
        200,
        20,
    ),
    RvcTrainingPresetId.HIGH_QUALITY: RvcTrainingPreset(
        RvcTrainingPresetId.HIGH_QUALITY,
        "High Quality",
        "Longer training with closer checkpoint review",
        300,
        25,
    ),
}


def recommend_rvc_training_settings(
    preset_id: RvcTrainingPresetId,
    *,
    current_epoch: int = 0,
    accelerated: bool = True,
    adapter_memory_bytes: int = 0,
) -> RvcTrainingRecommendation:
    if preset_id == RvcTrainingPresetId.CUSTOM:
        raise ValueError("Custom training settings do not have a fixed recommendation.")
    preset = TRAINING_PRESETS[preset_id]
    target_epoch = max(0, int(current_epoch)) + preset.epoch_increment
    return RvcTrainingRecommendation(
        preset=preset,
        target_epoch=target_epoch,
        batch_size=recommend_rvc_training_batch_size(
            accelerated=accelerated,
            adapter_memory_bytes=adapter_memory_bytes,
        ),
        checkpoint_interval=preset.checkpoint_interval,
    )


def recommend_rvc_training_batch_size(
    *,
    accelerated: bool,
    adapter_memory_bytes: int = 0,
) -> int:
    if not accelerated:
        return 2
    memory_gib = max(0, int(adapter_memory_bytes)) / 1024**3
    if memory_gib <= 0:
        return 4
    if memory_gib < 5:
        return 2
    if memory_gib < 8:
        return 3
    if memory_gib < 12:
        return 4
    return 6
