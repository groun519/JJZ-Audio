from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def build_waveform_peaks(path: Path, point_count: int) -> list[float]:
    if point_count <= 0:
        return []

    audio, _sample_rate = sf.read(path, always_2d=True, dtype="float32")
    if audio.size == 0:
        return []

    mono = np.mean(audio, axis=1)
    bucket_count = min(point_count, len(mono))
    bucket_size = max(1, len(mono) // bucket_count)
    trimmed = mono[: bucket_count * bucket_size]
    peaks = np.max(np.abs(trimmed.reshape(bucket_count, bucket_size)), axis=1)

    max_peak = float(np.max(peaks)) if peaks.size else 0.0
    if max_peak <= 0:
        return [0.0 for _ in range(bucket_count)]
    return (peaks / max_peak).tolist()
