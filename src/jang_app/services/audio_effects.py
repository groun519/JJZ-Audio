from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MasterProcessing:
    gain_db: int = 0
    stereo_width_percent: int = 100


def process_master_audio(audio: np.ndarray, processing: MasterProcessing) -> np.ndarray:
    if audio.ndim != 2:
        raise ValueError("Master processing requires a frames-by-channels audio array")

    result = audio.astype(np.float32, copy=True)
    result *= 10.0 ** (_clamp_gain(processing.gain_db) / 20.0)
    if result.shape[1] < 2:
        return result

    width = _clamp_width(processing.stereo_width_percent) / 100.0
    left = result[:, 0].copy()
    right = result[:, 1].copy()
    mid = (left + right) * 0.5
    side = (left - right) * 0.5 * width
    result[:, 0] = mid + side
    result[:, 1] = mid - side
    return result


def _clamp_gain(value: int) -> int:
    return max(-24, min(12, int(value)))


def _clamp_width(value: int) -> int:
    return max(0, min(200, int(value)))
