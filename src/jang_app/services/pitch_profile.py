from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PitchHistogramBin:
    midi_note: int
    note_name: str
    count: int


@dataclass(frozen=True)
class PitchCoverageRange:
    low_midi: int
    high_midi: int
    sample_ratio: float


def midi_note_name(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    midi = int(round(float(value)))
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[midi % 12]}{midi // 12 - 1}"


def estimate_pitch_midi(frame: np.ndarray, sample_rate: int) -> float | None:
    stride = max(1, round(sample_rate / 16000))
    signal = np.asarray(frame[::stride], dtype=np.float64)
    effective_rate = sample_rate / stride
    signal -= np.mean(signal)
    energy = float(np.dot(signal, signal))
    if energy <= 1e-8:
        return None
    signal *= np.hanning(len(signal))
    fft_size = 1 << max(1, (len(signal) * 2 - 1).bit_length())
    spectrum = np.fft.rfft(signal, fft_size)
    correlation = np.fft.irfft(spectrum * np.conjugate(spectrum), fft_size)[: len(signal)]
    if correlation[0] <= 0:
        return None
    min_lag = max(1, math.floor(effective_rate / 1100))
    max_lag = min(len(correlation) - 1, math.ceil(effective_rate / 65))
    if max_lag <= min_lag:
        return None
    search = correlation[min_lag : max_lag + 1]
    lag = min_lag + int(np.argmax(search))
    confidence = float(correlation[lag] / correlation[0])
    if confidence < 0.30:
        return None
    frequency = effective_rate / lag
    if not 65 <= frequency <= 1100:
        return None
    return 69.0 + 12.0 * math.log2(frequency / 440.0)


def correct_isolated_octave_errors(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) < 5:
        return values
    corrected = list(values)
    for index in range(2, len(values) - 2):
        neighbors = np.asarray(
            (*values[index - 2 : index], *values[index + 1 : index + 3]),
            dtype=np.float64,
        )
        if float(np.ptp(neighbors)) > 4.0:
            continue
        reference = float(np.median(neighbors))
        original = values[index]
        candidates = (original - 12.0, original + 12.0)
        replacement = min(candidates, key=lambda value: abs(value - reference))
        if 9.0 <= abs(original - reference) <= 15.0 and abs(replacement - reference) <= 2.5:
            corrected[index] = replacement
    return tuple(corrected)


def pitch_histogram(pitch: np.ndarray) -> tuple[PitchHistogramBin, ...]:
    if not pitch.size:
        return ()
    low = max(0, math.floor(float(np.percentile(pitch, 1))))
    high = min(127, math.ceil(float(np.percentile(pitch, 99))))
    rounded = np.rint(pitch).astype(np.int16)
    return tuple(
        PitchHistogramBin(note, midi_note_name(note), int(np.count_nonzero(rounded == note)))
        for note in range(low, high + 1)
    )


def pitch_coverage_ranges(
    histogram: tuple[PitchHistogramBin, ...],
) -> tuple[PitchCoverageRange, ...]:
    if not histogram:
        return ()
    counts = np.asarray([item.count for item in histogram], dtype=np.float64)
    total = float(np.sum(counts))
    if total <= 0:
        return ()
    smoothed = np.convolve(
        np.pad(counts, (1, 1)),
        np.asarray((0.25, 0.5, 0.25)),
        mode="valid",
    )
    threshold = max(1.0, float(np.max(smoothed)) * 0.15)
    covered = smoothed >= threshold
    _bridge_short_pitch_gaps(covered, max_gap=2)

    ranges: list[PitchCoverageRange] = []
    start: int | None = None
    for index, is_covered in enumerate((*covered, False)):
        if is_covered and start is None:
            start = index
            continue
        if is_covered or start is None:
            continue
        end = index - 1
        dense = np.flatnonzero(counts[start : end + 1] >= max(1.0, threshold * 0.5))
        if dense.size:
            low_index = start + int(dense[0])
            high_index = start + int(dense[-1])
            sample_count = float(np.sum(counts[low_index : high_index + 1]))
            sample_ratio = sample_count / total
            if sample_ratio >= 0.03:
                ranges.append(
                    PitchCoverageRange(
                        histogram[low_index].midi_note,
                        histogram[high_index].midi_note,
                        sample_ratio,
                    )
                )
        start = None
    return tuple(
        sorted(
            ranges,
            key=lambda item: (-item.sample_ratio, item.low_midi),
        )[:3]
    )


def primary_pitch_center(
    pitch: np.ndarray,
    ranges: tuple[PitchCoverageRange, ...],
) -> float | None:
    if not pitch.size or not ranges:
        return None
    primary = ranges[0]
    selected = pitch[
        (pitch >= primary.low_midi - 0.5)
        & (pitch <= primary.high_midi + 0.5)
    ]
    return float(np.median(selected)) if selected.size else None


def recommended_pitch_shift(model_center_midi: float, source_center_midi: float) -> int:
    return round(model_center_midi - source_center_midi)


def _bridge_short_pitch_gaps(covered: np.ndarray, *, max_gap: int) -> None:
    index = 1
    while index < len(covered) - 1:
        if covered[index]:
            index += 1
            continue
        start = index
        while index < len(covered) and not covered[index]:
            index += 1
        if (
            start > 0
            and index < len(covered)
            and covered[start - 1]
            and covered[index]
            and index - start <= max_gap
        ):
            covered[start:index] = True
