from __future__ import annotations

import math

import numpy as np

from jang_app.services.studio_session import StudioReverbSettings


_PROCESS_BLOCK_FRAMES = 128
_COMB_SECONDS = (0.0311, 0.0367, 0.0413, 0.0461)


class RealtimeReverb:
    """Low-latency preview reverb with persistent delay state."""

    def __init__(self, sample_rate: int, settings: StudioReverbSettings) -> None:
        self._sample_rate = max(1, int(sample_rate))
        self._settings = settings
        self._delays: tuple[_FeedbackDelay, ...] = ()
        self._feedback: tuple[float, ...] = ()
        self._configure(settings, reset=True)

    def update(self, settings: StudioReverbSettings) -> None:
        reset = self._delay_frames(settings) != tuple(delay.frame_count for delay in self._delays)
        self._settings = settings
        self._configure(settings, reset=reset)

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = _stereo(audio)
        if source.shape[0] == 0:
            return source
        output = np.empty_like(source)
        for start in range(0, source.shape[0], _PROCESS_BLOCK_FRAMES):
            end = min(source.shape[0], start + _PROCESS_BLOCK_FRAMES)
            output[start:end] = self._process_block(source[start:end])
        return output

    def _process_block(self, source: np.ndarray) -> np.ndarray:
        settings = self._settings
        crossfed = np.empty_like(source)
        crossfed[:, 0] = source[:, 0] + source[:, 1] * 0.16
        crossfed[:, 1] = source[:, 1] + source[:, 0] * 0.16
        combs = tuple(
            delay.process(crossfed, feedback)
            for delay, feedback in zip(self._delays, self._feedback, strict=True)
        )
        early = (combs[0] + combs[1]) * 0.5
        late = sum(combs[2:], np.zeros_like(source)) * 0.5
        brightness = max(0.0, min(1.0, settings.brightness_percent / 100.0))
        tone_gain = math.sqrt(
            _db_gain((settings.early_low_gain_db + settings.reverb_low_gain_db) * 0.5)
            * _db_gain((settings.early_high_gain_db + settings.reverb_high_gain_db) * 0.5)
        )
        distance_gain = 1.0 / (1.0 + max(0.0, settings.distance_m) * 0.08)
        wet = (
            early * _db_gain(settings.early_gain_db)
            + late * _db_gain(settings.reverb_gain_db) * (0.55 + brightness * 0.9)
        ) * tone_gain * distance_gain
        wet_mix = max(0.0, min(1.0, settings.dry_wet_percent / 100.0))
        direct = source * _db_gain(settings.direct_gain_db)
        return np.clip(
            direct * (1.0 - wet_mix) + wet * wet_mix,
            -8.0,
            8.0,
        ).astype(np.float32, copy=False)

    def _configure(self, settings: StudioReverbSettings, *, reset: bool) -> None:
        frames = self._delay_frames(settings)
        if reset:
            self._delays = tuple(_FeedbackDelay(frame_count) for frame_count in frames)
        decay_seconds = max(0.1, settings.decay_ms / 1_000.0)
        self._feedback = tuple(
            max(0.05, min(0.985, math.pow(10.0, -3.0 * frame_count / (self._sample_rate * decay_seconds))))
            for frame_count in frames
        )

    def _delay_frames(self, settings: StudioReverbSettings) -> tuple[int, ...]:
        room_scale = math.pow(
            max(1.0, settings.room_height_m * settings.room_length_m * settings.room_width_m)
            / 50.0,
            1.0 / 6.0,
        )
        pre_delay = max(0, round(settings.pre_delay_ms * self._sample_rate / 1_000.0))
        minimum = _PROCESS_BLOCK_FRAMES + 1
        return tuple(
            max(minimum, round(seconds * room_scale * self._sample_rate) + pre_delay)
            for seconds in _COMB_SECONDS
        )


class _FeedbackDelay:
    def __init__(self, frame_count: int) -> None:
        self.frame_count = max(_PROCESS_BLOCK_FRAMES + 1, int(frame_count))
        self._buffer = np.zeros((self.frame_count, 2), dtype=np.float32)
        self._position = 0

    def process(self, source: np.ndarray, feedback: float) -> np.ndarray:
        frame_count = source.shape[0]
        indices = (np.arange(frame_count) + self._position) % self.frame_count
        delayed = self._buffer[indices].copy()
        self._buffer[indices] = source + delayed * feedback
        self._position = (self._position + frame_count) % self.frame_count
        return delayed


def _stereo(audio: np.ndarray) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        source = source[:, None]
    if source.shape[1] == 1:
        return np.repeat(source, 2, axis=1)
    return source[:, :2]


def _db_gain(value: float) -> float:
    return math.pow(10.0, max(-60.0, min(6.0, float(value))) / 20.0)
