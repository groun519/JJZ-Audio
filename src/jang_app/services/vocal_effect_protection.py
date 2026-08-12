from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


_ANALYSIS_WINDOW_MS = 50
_ACTIVE_FLOOR_DB = -48.0
_RELATIVE_ACTIVE_FLOOR = 0.04
_COLLAPSE_START_RATIO = 0.55
_COLLAPSE_FULL_RATIO = 0.45
_DEFAULT_TARGET_RATIO = 0.88
_MIN_TARGET_RATIO = 0.82
_MAX_TARGET_RATIO = 0.92
_MAX_DRY_GAIN = 3.0
_MAX_RESTORE_BLEND = 0.90
_ATTACK_MS = 25
_RELEASE_MS = 180


class VocalEffectProtectionError(RuntimeError):
    """Raised when wet and effect-reduced vocals cannot be safely combined."""


@dataclass(frozen=True)
class VocalEffectProtectionReport:
    sample_rate: int
    channels: int
    frames: int
    analysis_windows: int
    protected_windows: int
    severe_collapse_windows: int
    active_threshold_db: float
    average_restore_blend: float
    maximum_restore_blend: float
    average_dry_gain: float
    maximum_dry_gain: float

    @property
    def detail(self) -> str:
        return (
            f"vocal-protected {self.protected_windows}/{self.analysis_windows} windows; "
            f"severe {self.severe_collapse_windows}; "
            f"blend avg {self.average_restore_blend:.3f} "
            f"max {self.maximum_restore_blend:.3f}; "
            f"dry gain avg {self.average_dry_gain:.3f} "
            f"max {self.maximum_dry_gain:.3f}; "
            f"active floor {self.active_threshold_db:.1f} dBFS"
        )


def protect_effect_removed_vocals(
    wet_vocals_path: Path,
    dry_vocals_path: Path,
    output_path: Path,
) -> VocalEffectProtectionReport:
    wet_path = wet_vocals_path.expanduser().resolve()
    dry_path = dry_vocals_path.expanduser().resolve()
    target = output_path.expanduser().resolve()
    if wet_path == dry_path:
        raise VocalEffectProtectionError("Wet and effect-reduced vocals must be separate files.")

    wet_info, dry_info = _matching_audio_info(wet_path, dry_path)
    window_frames = max(1, round(wet_info.samplerate * _ANALYSIS_WINDOW_MS / 1_000))
    wet_levels, dry_levels = _measure_window_rms(
        wet_path,
        dry_path,
        frames=wet_info.frames,
        window_frames=window_frames,
    )
    gains, weights, active_threshold, severe_windows = _build_protection_controls(
        wet_levels,
        dry_levels,
        window_seconds=window_frames / wet_info.samplerate,
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".vocal-protection.tmp.wav")
    temporary.unlink(missing_ok=True)
    try:
        _write_protected_audio(
            wet_path,
            dry_path,
            temporary,
            sample_rate=wet_info.samplerate,
            channels=wet_info.channels,
            frames=wet_info.frames,
            window_frames=window_frames,
            gains=gains,
            weights=weights,
        )
        os.replace(temporary, target)
    except (OSError, RuntimeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, VocalEffectProtectionError):
            raise
        raise VocalEffectProtectionError("Could not write vocal-protected audio.") from exc

    protected_mask = (gains > 1.01) | (weights > 0.005)
    protected_weights = weights[protected_mask]
    protected_gains = gains[protected_mask]
    return VocalEffectProtectionReport(
        sample_rate=wet_info.samplerate,
        channels=wet_info.channels,
        frames=wet_info.frames,
        analysis_windows=len(weights),
        protected_windows=int(np.count_nonzero(protected_mask)),
        severe_collapse_windows=severe_windows,
        active_threshold_db=_amplitude_to_db(active_threshold),
        average_restore_blend=(
            float(np.mean(protected_weights)) if protected_weights.size else 0.0
        ),
        maximum_restore_blend=float(np.max(weights)) if weights.size else 0.0,
        average_dry_gain=(
            float(np.mean(protected_gains)) if protected_gains.size else 1.0
        ),
        maximum_dry_gain=float(np.max(gains)) if gains.size else 1.0,
    )


def _matching_audio_info(wet_path: Path, dry_path: Path):
    try:
        wet_info = sf.info(wet_path)
        dry_info = sf.info(dry_path)
    except (OSError, RuntimeError) as exc:
        raise VocalEffectProtectionError("Could not read effect-removal vocal stems.") from exc
    wet_shape = (wet_info.samplerate, wet_info.channels, wet_info.frames)
    dry_shape = (dry_info.samplerate, dry_info.channels, dry_info.frames)
    if wet_shape != dry_shape:
        raise VocalEffectProtectionError(
            "Effect-removal vocal stems are not aligned: "
            f"wet {wet_shape}, dry {dry_shape}."
        )
    return wet_info, dry_info


def _measure_window_rms(
    wet_path: Path,
    dry_path: Path,
    *,
    frames: int,
    window_frames: int,
) -> tuple[np.ndarray, np.ndarray]:
    wet_levels: list[float] = []
    dry_levels: list[float] = []
    try:
        with sf.SoundFile(wet_path) as wet_file, sf.SoundFile(dry_path) as dry_file:
            remaining = frames
            while remaining > 0:
                block_frames = min(window_frames, remaining)
                wet = wet_file.read(block_frames, dtype="float32", always_2d=True)
                dry = dry_file.read(block_frames, dtype="float32", always_2d=True)
                if len(wet) != block_frames or len(dry) != block_frames:
                    raise VocalEffectProtectionError(
                        "An effect-removal vocal stem ended before its declared length."
                    )
                wet_levels.append(_rms(wet))
                dry_levels.append(_rms(dry))
                remaining -= block_frames
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, VocalEffectProtectionError):
            raise
        raise VocalEffectProtectionError("Could not analyze effect-removal vocals.") from exc
    return np.asarray(wet_levels, dtype=np.float64), np.asarray(
        dry_levels,
        dtype=np.float64,
    )


def _build_protection_controls(
    wet_levels: np.ndarray,
    dry_levels: np.ndarray,
    *,
    window_seconds: float,
) -> tuple[np.ndarray, np.ndarray, float, int]:
    if wet_levels.shape != dry_levels.shape:
        raise VocalEffectProtectionError("Vocal level envelopes are not aligned.")
    if wet_levels.size == 0:
        return (
            np.ones(0, dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            _db_to_amplitude(_ACTIVE_FLOOR_DB),
            0,
        )

    relative_floor = float(np.percentile(wet_levels, 90)) * _RELATIVE_ACTIVE_FLOOR
    active_threshold = max(_db_to_amplitude(_ACTIVE_FLOOR_DB), relative_floor)
    activity = np.clip(
        (wet_levels - active_threshold) / max(active_threshold, 1e-9),
        0.0,
        1.0,
    )
    ratio = dry_levels / np.maximum(wet_levels, 1e-9)
    collapse = np.clip(
        (_COLLAPSE_START_RATIO - ratio)
        / (_COLLAPSE_START_RATIO - _COLLAPSE_FULL_RATIO),
        0.0,
        1.0,
    )
    restore_strength = _expand_neighbors(collapse * activity)
    target_ratio = _target_level_ratio(ratio, wet_levels, active_threshold)
    desired_ratio = ratio + restore_strength * np.maximum(0.0, target_ratio - ratio)

    safe_ratio = np.maximum(ratio, 1e-9)
    target_gains = np.clip(desired_ratio / safe_ratio, 1.0, _MAX_DRY_GAIN)
    effective_ratio = ratio * target_gains
    blend_denominator = np.maximum(1e-9, 1.0 - effective_ratio)
    target_weights = np.clip(
        (desired_ratio - effective_ratio) / blend_denominator,
        0.0,
        _MAX_RESTORE_BLEND,
    )
    gains = _smooth_control(
        target_gains,
        window_seconds,
        baseline=1.0,
        release_ms=80,
    )
    weights = _smooth_control(
        target_weights,
        window_seconds,
        baseline=0.0,
        release_ms=_RELEASE_MS,
    )
    severe_windows = int(
        np.count_nonzero((wet_levels >= active_threshold) & (ratio < 0.20))
    )
    return (
        gains.astype(np.float32),
        weights.astype(np.float32),
        active_threshold,
        severe_windows,
    )


def _target_level_ratio(
    ratio: np.ndarray,
    wet_levels: np.ndarray,
    active_threshold: float,
) -> float:
    normal = ratio[
        (wet_levels >= active_threshold)
        & (ratio >= 0.75)
        & (ratio <= 1.25)
    ]
    if normal.size == 0:
        return _DEFAULT_TARGET_RATIO
    return float(
        np.clip(
            float(np.median(normal)) * 0.90,
            _MIN_TARGET_RATIO,
            _MAX_TARGET_RATIO,
        )
    )


def _expand_neighbors(values: np.ndarray) -> np.ndarray:
    if values.size < 2:
        return values.copy()
    expanded = values.copy()
    expanded[1:] = np.maximum(expanded[1:], values[:-1])
    expanded[:-1] = np.maximum(expanded[:-1], values[1:])
    return expanded


def _smooth_control(
    values: np.ndarray,
    window_seconds: float,
    *,
    baseline: float,
    release_ms: int,
) -> np.ndarray:
    if values.size == 0:
        return values.copy()
    attack = 1.0 - math.exp(-window_seconds / (_ATTACK_MS / 1_000))
    release = 1.0 - math.exp(-window_seconds / (release_ms / 1_000))
    smoothed = np.zeros_like(values)
    current = baseline
    for index, target in enumerate(values):
        coefficient = attack if target > current else release
        current += coefficient * (float(target) - current)
        smoothed[index] = current
    return smoothed


def _write_protected_audio(
    wet_path: Path,
    dry_path: Path,
    target: Path,
    *,
    sample_rate: int,
    channels: int,
    frames: int,
    window_frames: int,
    gains: np.ndarray,
    weights: np.ndarray,
) -> None:
    try:
        with (
            sf.SoundFile(wet_path) as wet_file,
            sf.SoundFile(dry_path) as dry_file,
            sf.SoundFile(
                target,
                mode="w",
                samplerate=sample_rate,
                channels=channels,
                subtype="FLOAT",
            ) as output_file,
        ):
            remaining = frames
            previous_gain = float(gains[0]) if gains.size else 1.0
            previous_weight = float(weights[0]) if weights.size else 0.0
            index = 0
            while remaining > 0:
                block_frames = min(window_frames, remaining)
                wet = wet_file.read(block_frames, dtype="float32", always_2d=True)
                dry = dry_file.read(block_frames, dtype="float32", always_2d=True)
                if len(wet) != block_frames or len(dry) != block_frames:
                    raise VocalEffectProtectionError(
                        "An effect-removal vocal stem ended during protection."
                    )
                current_weight = float(weights[index]) if index < len(weights) else 0.0
                current_gain = float(gains[index]) if index < len(gains) else 1.0
                gain = np.linspace(
                    previous_gain,
                    current_gain,
                    block_frames,
                    endpoint=True,
                    dtype=np.float32,
                )[:, None]
                blend = np.linspace(
                    previous_weight,
                    current_weight,
                    block_frames,
                    endpoint=True,
                    dtype=np.float32,
                )[:, None]
                compensated_dry = dry * gain
                output_file.write(
                    compensated_dry + blend * (wet - compensated_dry)
                )
                previous_gain = current_gain
                previous_weight = current_weight
                remaining -= block_frames
                index += 1
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, VocalEffectProtectionError):
            raise
        raise VocalEffectProtectionError("Could not process effect-removal vocals.") from exc


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def _db_to_amplitude(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _amplitude_to_db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-9))
