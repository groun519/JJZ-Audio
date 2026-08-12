from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from jang_app.services.studio_session import StudioReverbSettings


_SPEED_OF_SOUND_M_S = 343.0
_FDN_LINE_COUNT = 8
_INV_SQRT_EIGHT = 1.0 / math.sqrt(8.0)


def apply_reverb(
    audio: np.ndarray,
    sample_rate: int,
    settings: StudioReverbSettings,
) -> np.ndarray:
    """Render deterministic room reverb without modifying the source array."""
    source = _stereo_audio(audio)
    if source.shape[0] == 0 or sample_rate <= 0:
        return source

    wet_mix = max(0.0, min(1.0, settings.dry_wet_percent / 100.0))
    direct_gain = _db_gain(settings.direct_gain_db)
    if wet_mix <= 0.0:
        return np.asarray(audio, dtype=np.float32).copy() * direct_gain

    early_ir, late_ir = _room_impulses(sample_rate, settings)
    early = _convolve_stereo(source, early_ir) * _db_gain(settings.early_gain_db)
    late = _convolve_stereo(source, late_ir) * _db_gain(settings.reverb_gain_db)
    output_frames = max(source.shape[0], early.shape[0], late.shape[0])
    output = np.zeros((output_frames, 2), dtype=np.float32)
    output[: source.shape[0]] += source * ((1.0 - wet_mix) * direct_gain)
    output[: early.shape[0]] += early * wet_mix
    output[: late.shape[0]] += late * wet_mix
    return _safe_audio(output)


def _room_impulses(
    sample_rate: int,
    settings: StudioReverbSettings,
) -> tuple[np.ndarray, np.ndarray]:
    if sample_rate <= 0:
        empty = np.zeros((0, 2), dtype=np.float32)
        return empty, empty
    impulse_frames = _impulse_frame_count(sample_rate, settings)
    early = _early_reflection_impulse(sample_rate, impulse_frames, settings)
    late = _late_reverb_impulse(
        sample_rate,
        impulse_frames,
        float(settings.room_height_m),
        float(settings.room_length_m),
        float(settings.room_width_m),
        int(settings.pre_delay_ms),
        int(settings.decay_ms),
        int(settings.brightness_percent),
        int(settings.reverb_low_hz),
        int(settings.reverb_high_hz),
        float(settings.reverb_low_gain_db),
        float(settings.reverb_high_gain_db),
    )
    return early, late


def _impulse_frame_count(sample_rate: int, settings: StudioReverbSettings) -> int:
    decay_seconds = max(0.1, float(settings.decay_ms) / 1_000.0)
    positive_pre_delay = max(0.0, float(settings.pre_delay_ms) / 1_000.0)
    late_horizon = positive_pre_delay + decay_seconds * 1.15
    early_horizon = positive_pre_delay + 0.45
    return max(2, round(max(late_horizon, early_horizon) * sample_rate))


def _early_reflection_impulse(
    sample_rate: int,
    impulse_frames: int,
    settings: StudioReverbSettings,
) -> np.ndarray:
    early = np.zeros((impulse_frames, 2), dtype=np.float32)
    height = max(1.0, float(settings.room_height_m))
    length = max(1.0, float(settings.room_length_m))
    width = max(1.0, float(settings.room_width_m))
    source_distance = max(0.0, float(settings.distance_m))
    pre_delay_frames = round(float(settings.pre_delay_ms) * sample_rate / 1_000.0)
    modulation = max(0.0, min(1.0, float(settings.modulation_percent) / 100.0))
    seed = int(
        height * 101
        + length * 211
        + width * 307
        + source_distance * 401
    )
    rng = np.random.default_rng(seed)

    # First- and second-order image paths provide stable, room-shaped reflections.
    paths = (
        (2.0 * width, 1, -0.82),
        (2.0 * length, 1, 0.82),
        (2.0 * height, 1, 0.0),
        (2.0 * math.hypot(width, height), 2, -0.48),
        (2.0 * math.hypot(length, height), 2, 0.48),
        (2.0 * math.hypot(width, length), 2, -0.16),
        (2.0 * math.sqrt(width * width + length * length + height * height), 3, 0.16),
        (width + length + height, 3, 0.68),
    )
    for base_path, order, pan in paths:
        path_m = math.hypot(base_path, source_distance)
        frame = pre_delay_frames + round(path_m * sample_rate / _SPEED_OF_SOUND_M_S)
        reflection_gain = math.pow(0.68, order) / (1.0 + path_m * 0.045)
        left_gain = math.cos((pan + 1.0) * math.pi / 4.0)
        right_gain = math.sin((pan + 1.0) * math.pi / 4.0)
        for offset, phase_gain in _reflection_phase_cluster(
            sample_rate,
            modulation,
            rng,
        ):
            tap_frame = max(0, min(impulse_frames - 1, frame + offset))
            early[tap_frame, 0] += reflection_gain * phase_gain * left_gain
            early[tap_frame, 1] += reflection_gain * phase_gain * right_gain

    return _tone_shape(
        early,
        sample_rate,
        settings.early_low_hz,
        settings.early_high_hz,
        settings.early_low_gain_db,
        settings.early_high_gain_db,
    )


def _reflection_phase_cluster(
    sample_rate: int,
    modulation: float,
    rng: np.random.Generator,
) -> tuple[tuple[int, float], ...]:
    if modulation <= 0.0:
        return ((0, 1.0),)
    spread = max(1, round(sample_rate * 0.0025 * modulation))
    offsets = np.asarray(
        (
            0,
            rng.integers(-spread, 0),
            rng.integers(1, spread + 1),
            rng.integers(-spread, spread + 1),
        ),
        dtype=np.int32,
    )
    weights = np.asarray((0.82, 0.31, -0.27, 0.19), dtype=np.float64)
    weights /= math.sqrt(float(np.sum(weights * weights)))
    return tuple((int(offset), float(weight)) for offset, weight in zip(offsets, weights))


@lru_cache(maxsize=48)
def _late_reverb_impulse(
    sample_rate: int,
    impulse_frames: int,
    room_height_m: float,
    room_length_m: float,
    room_width_m: float,
    pre_delay_ms: int,
    decay_ms: int,
    brightness_percent: int,
    low_hz: int,
    high_hz: int,
    low_gain_db: float,
    high_gain_db: float,
) -> np.ndarray:
    late = np.zeros((impulse_frames, 2), dtype=np.float32)
    body_frames = max(2, round(max(100, decay_ms) * sample_rate / 1_000.0 * 1.08))
    body = _fdn_room_tail(
        sample_rate,
        body_frames,
        room_height_m,
        room_length_m,
        room_width_m,
        max(0.1, decay_ms / 1_000.0),
        brightness_percent,
    )
    shift = round(pre_delay_ms * sample_rate / 1_000.0)
    source_start = max(0, -shift)
    output_start = max(0, shift)
    count = min(body.shape[0] - source_start, impulse_frames - output_start)
    if count > 0:
        late[output_start : output_start + count] = body[source_start : source_start + count]
    shaped = _tone_shape(
        late,
        sample_rate,
        low_hz,
        high_hz,
        low_gain_db,
        high_gain_db,
    )
    shaped.setflags(write=False)
    return shaped


def _fdn_room_tail(
    sample_rate: int,
    frame_count: int,
    room_height_m: float,
    room_length_m: float,
    room_width_m: float,
    decay_seconds: float,
    brightness_percent: int,
) -> np.ndarray:
    delay_lengths = _room_delay_lengths(
        sample_rate,
        frame_count,
        room_height_m,
        room_length_m,
        room_width_m,
    )
    buffers = [np.zeros(length, dtype=np.float32) for length in delay_lengths]
    indices = np.zeros(_FDN_LINE_COUNT, dtype=np.int32)
    taps = np.zeros(_FDN_LINE_COUNT, dtype=np.float64)
    damped = np.zeros(_FDN_LINE_COUNT, dtype=np.float64)
    weighted = np.zeros(_FDN_LINE_COUNT, dtype=np.float64)
    mixed = np.zeros(_FDN_LINE_COUNT, dtype=np.float64)
    feedback_gains = np.asarray(
        [
            math.pow(10.0, -3.0 * length / (sample_rate * decay_seconds))
            for length in delay_lengths
        ],
        dtype=np.float64,
    )
    brightness = max(0.0, min(1.0, brightness_percent / 100.0))
    damping_alpha = 0.055 + math.pow(brightness, 1.6) * 0.945
    left_mix = np.asarray((1, -1, 1, -1, 1, -1, 1, -1), dtype=np.float64)
    right_mix = np.asarray((1, 1, -1, -1, -1, -1, 1, 1), dtype=np.float64)
    left_mix *= _INV_SQRT_EIGHT
    right_mix *= _INV_SQRT_EIGHT
    injection = np.asarray((1, -1, -1, 1, -1, 1, 1, -1), dtype=np.float64)
    injection *= _INV_SQRT_EIGHT
    output = np.zeros((frame_count, 2), dtype=np.float32)

    seed = int(room_height_m * 101 + room_length_m * 211 + room_width_m * 307)
    rng = np.random.default_rng(seed)
    diffusion_frames = min(frame_count, max(1, round(sample_rate * 0.006)))
    diffusion = rng.standard_normal((diffusion_frames, _FDN_LINE_COUNT))
    diffusion *= np.exp(-np.arange(diffusion_frames)[:, None] / max(1, diffusion_frames * 0.32))
    diffusion *= 0.025
    diffusion[0] += injection * 0.72

    for frame in range(frame_count):
        for line in range(_FDN_LINE_COUNT):
            taps[line] = buffers[line][indices[line]]
        damped += damping_alpha * (taps - damped)
        np.multiply(damped, feedback_gains, out=weighted)
        _hadamard_eight(weighted, mixed)
        if frame < diffusion_frames:
            mixed += diffusion[frame]
        for line in range(_FDN_LINE_COUNT):
            buffers[line][indices[line]] = mixed[line]
            indices[line] += 1
            if indices[line] == delay_lengths[line]:
                indices[line] = 0
        output[frame, 0] = float(np.dot(taps, left_mix))
        output[frame, 1] = float(np.dot(taps, right_mix))

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.0:
        output *= min(1.0, 0.72 / peak)
    return output


def _room_delay_lengths(
    sample_rate: int,
    frame_count: int,
    height: float,
    length: float,
    width: float,
) -> tuple[int, ...]:
    paths = (
        width * 0.71 + height * 0.29,
        length * 0.67 + height * 0.37,
        math.hypot(width, height) * 0.61,
        math.hypot(length, height) * 0.73,
        math.hypot(width, length) * 0.53,
        (width + length + height) * 0.41,
        math.sqrt(width * width + length * length + height * height) * 0.79,
        width * 0.37 + length * 0.43 + height * 0.47,
    )
    minimum = max(11, round(sample_rate * 0.006))
    maximum = max(minimum + 2, min(frame_count // 3, round(sample_rate * 0.085)))
    used: set[int] = set()
    delays: list[int] = []
    for path in paths:
        target = max(minimum, min(maximum, round(path * sample_rate / _SPEED_OF_SOUND_M_S)))
        delay = _next_prime(target)
        while delay in used:
            delay = _next_prime(delay + 1)
        used.add(delay)
        delays.append(delay)
    return tuple(delays)


def _next_prime(value: int) -> int:
    candidate = max(3, int(value))
    if candidate % 2 == 0:
        candidate += 1
    while True:
        limit = int(math.sqrt(candidate))
        if all(candidate % divisor for divisor in range(3, limit + 1, 2)):
            return candidate
        candidate += 2


def _hadamard_eight(source: np.ndarray, output: np.ndarray) -> None:
    a0, a1 = source[0] + source[1], source[0] - source[1]
    a2, a3 = source[2] + source[3], source[2] - source[3]
    a4, a5 = source[4] + source[5], source[4] - source[5]
    a6, a7 = source[6] + source[7], source[6] - source[7]
    b0, b1 = a0 + a2, a1 + a3
    b2, b3 = a0 - a2, a1 - a3
    b4, b5 = a4 + a6, a5 + a7
    b6, b7 = a4 - a6, a5 - a7
    output[:] = (
        b0 + b4,
        b1 + b5,
        b2 + b6,
        b3 + b7,
        b0 - b4,
        b1 - b5,
        b2 - b6,
        b3 - b7,
    )
    output *= _INV_SQRT_EIGHT


def _tone_shape(
    audio: np.ndarray,
    sample_rate: int,
    low_hz: int,
    high_hz: int,
    low_gain_db: float,
    high_gain_db: float,
) -> np.ndarray:
    if audio.shape[0] == 0:
        return audio
    spectrum = np.fft.rfft(audio, axis=0)
    frequencies = np.fft.rfftfreq(audio.shape[0], 1.0 / sample_rate)
    gains = np.ones(frequencies.shape[0], dtype=np.float64)
    low_width = max(20.0, float(low_hz) * 0.5)
    high_width = max(200.0, float(high_hz) * 0.25)
    low_blend = 1.0 / (1.0 + np.exp(np.clip((frequencies - low_hz) / low_width, -60, 60)))
    high_blend = 1.0 / (1.0 + np.exp(np.clip((high_hz - frequencies) / high_width, -60, 60)))
    gains *= 1.0 + (_db_gain(low_gain_db) - 1.0) * low_blend
    gains *= 1.0 + (_db_gain(high_gain_db) - 1.0) * high_blend
    shaped = np.fft.irfft(spectrum * gains[:, None], n=audio.shape[0], axis=0)
    return shaped.astype(np.float32)


def _convolve_stereo(audio: np.ndarray, impulse: np.ndarray) -> np.ndarray:
    output_frames = audio.shape[0] + impulse.shape[0] - 1
    fft_frames = 1 << max(1, output_frames - 1).bit_length()
    output = np.empty((output_frames, 2), dtype=np.float32)
    for channel in range(2):
        source_fft = np.fft.rfft(audio[:, channel], fft_frames)
        impulse_fft = np.fft.rfft(impulse[:, channel], fft_frames)
        output[:, channel] = np.fft.irfft(source_fft * impulse_fft, fft_frames)[:output_frames]
    return output


def _stereo_audio(audio: np.ndarray) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        source = source[:, None]
    if source.ndim != 2:
        raise ValueError("Audio must be a one- or two-dimensional array.")
    if source.shape[1] == 1:
        return np.repeat(source, 2, axis=1)
    return source[:, :2].copy()


def _safe_audio(audio: np.ndarray) -> np.ndarray:
    safe = np.nan_to_num(audio, nan=0.0, posinf=8.0, neginf=-8.0)
    return np.clip(safe, -8.0, 8.0).astype(np.float32, copy=False)


def _db_gain(value: float) -> float:
    return math.pow(10.0, max(-60.0, min(6.0, float(value))) / 20.0)
