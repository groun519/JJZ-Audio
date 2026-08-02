from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def waveform_cache_key(path: Path, point_count: int) -> tuple[str, int, int, int]:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_mtime_ns, stat.st_size, point_count)


def build_waveform_peaks(path: Path, point_count: int) -> list[float]:
    if point_count <= 0:
        return []

    with sf.SoundFile(path) as audio:
        frame_count = len(audio)
        if frame_count <= 0:
            return []
        bucket_count = min(point_count, frame_count)
        bucket_size = max(1, frame_count // bucket_count)
        peaks = _stream_peaks(audio, bucket_count, bucket_size)

    max_peak = float(np.max(peaks)) if peaks.size else 0.0
    if max_peak <= 0:
        return [0.0 for _ in range(bucket_count)]
    return (peaks / max_peak).tolist()


def _stream_peaks(audio: sf.SoundFile, bucket_count: int, bucket_size: int) -> np.ndarray:
    peaks = np.zeros(bucket_count, dtype=np.float32)
    usable_frames = bucket_count * bucket_size
    cursor = 0
    while cursor < usable_frames:
        block = audio.read(min(65536, usable_frames - cursor), always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1)
        block_cursor = 0
        while block_cursor < len(mono):
            bucket_index = cursor // bucket_size
            bucket_end = (bucket_index + 1) * bucket_size
            take = min(len(mono) - block_cursor, bucket_end - cursor)
            peaks[bucket_index] = max(
                peaks[bucket_index],
                float(np.max(np.abs(mono[block_cursor : block_cursor + take]))),
            )
            block_cursor += take
            cursor += take
    return peaks
