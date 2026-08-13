from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import soundfile as sf

from jang_app.services.pitch_profile import correct_isolated_octave_errors, estimate_pitch_midi


_FRAME_MS = 50
_SILENCE_FLOOR_DB = -55.0
_MAX_PITCH_SAMPLES = 3000


@dataclass(frozen=True)
class AudioPitchMetrics:
    duration_ms: int
    active_ratio: float
    rms_db: float
    peak_db: float
    clipping_ratio: float
    noise_floor_db: float | None
    signal_contrast_db: float | None
    pitch_midi_samples: tuple[float, ...]


def analyze_audio_signal(audio: sf.SoundFile) -> AudioPitchMetrics:
    sample_rate = audio.samplerate
    frame_size = max(1, round(sample_rate * _FRAME_MS / 1000))
    expected_frames = max(1, math.ceil(len(audio) / frame_size))
    pitch_stride = max(2, math.ceil(expected_frames / _MAX_PITCH_SAMPLES))
    carry = np.empty(0, dtype=np.float32)
    frame_levels: list[float] = []
    pitch_candidates: list[tuple[float, float]] = []
    sample_count = 0
    clipping_count = 0
    square_sum = 0.0
    peak = 0.0
    frame_index = 0
    previous_pitch_frame: np.ndarray | None = None

    while True:
        block = audio.read(frame_size * 256, always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1, dtype=np.float32)
        sample_count += len(mono)
        clipping_count += int(np.count_nonzero(np.abs(mono) >= 0.999))
        square_sum += float(np.sum(np.square(mono, dtype=np.float64)))
        peak = max(peak, float(np.max(np.abs(mono), initial=0.0)))
        if carry.size:
            mono = np.concatenate((carry, mono))
        complete = len(mono) // frame_size
        if complete:
            frames = mono[: complete * frame_size].reshape(complete, frame_size)
            rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
            levels = 20 * np.log10(np.maximum(rms, 1e-9))
            frame_levels.extend(float(level) for level in levels)
            for local_index, frame in enumerate(frames):
                absolute_index = frame_index + local_index
                pitch_frame = (
                    np.concatenate((previous_pitch_frame, frame))
                    if previous_pitch_frame is not None
                    else frame
                )
                previous_pitch_frame = frame.copy()
                if absolute_index % pitch_stride or levels[local_index] < _SILENCE_FLOOR_DB:
                    continue
                pitch = estimate_pitch_midi(pitch_frame, sample_rate)
                if pitch is not None:
                    pitch_candidates.append((float(levels[local_index]), pitch))
            frame_index += complete
        carry = mono[complete * frame_size :].copy()

    if carry.size:
        padded = np.pad(carry, (0, frame_size - len(carry)))
        rms = float(np.sqrt(np.mean(np.square(padded, dtype=np.float64))))
        level = 20 * math.log10(max(rms, 1e-9))
        frame_levels.append(level)
        if frame_index % pitch_stride == 0 and level >= _SILENCE_FLOOR_DB:
            pitch_frame = (
                np.concatenate((previous_pitch_frame, padded))
                if previous_pitch_frame is not None
                else padded
            )
            pitch = estimate_pitch_midi(pitch_frame, sample_rate)
            if pitch is not None:
                pitch_candidates.append((level, pitch))

    if sample_count <= 0 or not frame_levels:
        raise RuntimeError("Audio contains no readable samples.")
    levels = np.asarray(frame_levels, dtype=np.float64)
    upper_level = float(np.percentile(levels, 90))
    active_threshold = max(_SILENCE_FLOOR_DB, min(-35.0, upper_level - 25.0))
    active = levels >= active_threshold
    active_levels = levels[active]
    inactive_levels = levels[~active]
    has_quiet_reference = inactive_levels.size >= max(3, math.ceil(len(levels) * 0.05))
    noise_floor = max(-100.0, float(np.median(inactive_levels))) if has_quiet_reference else None
    signal_level = float(np.median(active_levels)) if active_levels.size else None
    signal_contrast = (
        min(80.0, max(0.0, signal_level - noise_floor))
        if signal_level is not None and noise_floor is not None
        else None
    )
    pitch_samples = correct_isolated_octave_errors(
        tuple(pitch for level, pitch in pitch_candidates if level >= active_threshold)
    )
    rms = math.sqrt(square_sum / sample_count)
    return AudioPitchMetrics(
        duration_ms=round(sample_count * 1000 / sample_rate),
        active_ratio=float(np.count_nonzero(active) / len(levels)),
        rms_db=20 * math.log10(max(rms, 1e-9)),
        peak_db=20 * math.log10(max(peak, 1e-9)),
        clipping_ratio=clipping_count / sample_count,
        noise_floor_db=noise_floor,
        signal_contrast_db=signal_contrast,
        pitch_midi_samples=pitch_samples,
    )
