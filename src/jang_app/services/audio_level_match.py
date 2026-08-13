from __future__ import annotations

import numpy as np

from jang_app.services.studio_session import StudioLevelMatchSettings


def apply_vocal_level_match(
    audio: np.ndarray,
    reference_audio: np.ndarray | None,
    sample_rate: int,
    settings: StudioLevelMatchSettings,
) -> np.ndarray:
    """Follow a reference vocal envelope while protecting silence and transients."""
    source, was_mono = _audio_matrix(audio)
    if reference_audio is None or source.shape[0] == 0 or sample_rate <= 0:
        return np.asarray(audio, dtype=np.float32).copy()
    reference, _reference_was_mono = _audio_matrix(reference_audio)
    shared_frames = min(source.shape[0], reference.shape[0])
    if shared_frames <= 0 or settings.strength_percent <= 0:
        return np.asarray(audio, dtype=np.float32).copy()

    hop_frames = max(1, round(sample_rate * 0.01))
    window_frames = max(hop_frames, round(sample_rate * settings.response_ms / 1_000))
    positions = np.arange(0, shared_frames, hop_frames, dtype=np.int64)
    if positions[-1] != shared_frames - 1:
        positions = np.append(positions, shared_frames - 1)
    source_rms = _sampled_rms(source[:shared_frames], positions, window_frames)
    reference_rms = _sampled_rms(reference[:shared_frames], positions, window_frames)
    floor = 10.0 ** (settings.silence_threshold_db / 20.0)
    valid = (source_rms >= floor) & (reference_rms >= floor)
    gain_db = np.zeros(positions.shape[0], dtype=np.float64)
    gain_db[valid] = 20.0 * np.log10(
        np.maximum(reference_rms[valid], 1e-8) / np.maximum(source_rms[valid], 1e-8)
    )
    gain_db *= settings.strength_percent / 100.0
    gain_db = np.clip(gain_db, -settings.max_correction_db, settings.max_correction_db)
    gain_db = _smooth_gain(gain_db, settings.response_ms, hop_frames, sample_rate)

    sample_positions = np.arange(shared_frames, dtype=np.float64)
    gain = np.power(10.0, np.interp(sample_positions, positions, gain_db) / 20.0)
    processed = source.copy()
    processed[:shared_frames] *= gain.astype(np.float32)[:, None]
    return processed[:, 0] if was_mono else processed


def _audio_matrix(audio: np.ndarray) -> tuple[np.ndarray, bool]:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        return source[:, None], True
    if source.ndim != 2:
        raise ValueError("Audio must be a mono or channel-based sample array.")
    return source, False


def _sampled_rms(
    audio: np.ndarray,
    positions: np.ndarray,
    window_frames: int,
) -> np.ndarray:
    power = np.mean(np.square(audio, dtype=np.float64), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(power, dtype=np.float64)))
    half_window = max(1, window_frames // 2)
    starts = np.maximum(0, positions - half_window)
    ends = np.minimum(audio.shape[0], positions + half_window + 1)
    means = (cumulative[ends] - cumulative[starts]) / np.maximum(1, ends - starts)
    return np.sqrt(np.maximum(means, 0.0))


def _smooth_gain(
    gain_db: np.ndarray,
    response_ms: int,
    hop_frames: int,
    sample_rate: int,
) -> np.ndarray:
    hop_ms = hop_frames * 1_000.0 / sample_rate
    smoothing_points = max(1, round(response_ms / max(hop_ms, 1.0) / 3.0))
    if smoothing_points <= 1:
        return gain_db
    kernel = np.hanning(smoothing_points * 2 + 1)
    kernel /= np.sum(kernel)
    padded = np.pad(gain_db, smoothing_points, mode="edge")
    return np.convolve(padded, kernel, mode="valid")
