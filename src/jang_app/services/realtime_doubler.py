from __future__ import annotations

import math

import numpy as np

from jang_app.services.studio_session import StudioDoublerSettings


_PROCESS_BLOCK_FRAMES = 32
_LEFT_RATE_HZ = 0.31
_RIGHT_RATE_HZ = 0.37
_MAX_DELAY_SECONDS = 0.12


class RealtimeDoubler:
    """Stereo vocal doubler based on two independently modulated delay taps."""

    def __init__(self, sample_rate: int, settings: StudioDoublerSettings) -> None:
        self._sample_rate = max(1, int(sample_rate))
        self._settings = settings
        self._buffer = np.zeros(
            max(_PROCESS_BLOCK_FRAMES * 2, math.ceil(self._sample_rate * _MAX_DELAY_SECONDS)),
            dtype=np.float32,
        )
        self._write_position = 0
        self._sample_position = 0

    def update(self, settings: StudioDoublerSettings) -> None:
        self._settings = settings

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = _stereo(audio)
        if source.shape[0] == 0:
            return source
        wet = np.empty_like(source)
        center = np.mean(source, axis=1, dtype=np.float32)
        for start in range(0, source.shape[0], _PROCESS_BLOCK_FRAMES):
            end = min(source.shape[0], start + _PROCESS_BLOCK_FRAMES)
            wet[start:end] = self._process_block(center[start:end])

        mix = _ratio(self._settings.dry_wet_percent)
        if mix <= 0.0:
            return source.copy()
        dry_gain = math.cos(mix * math.pi / 2.0)
        wet_gain = math.sin(mix * math.pi / 2.0)
        return np.clip(source * dry_gain + wet * wet_gain, -8.0, 8.0).astype(
            np.float32,
            copy=False,
        )

    def _process_block(self, center: np.ndarray) -> np.ndarray:
        frame_count = center.shape[0]
        write_indexes = (
            self._write_position + np.arange(frame_count, dtype=np.int64)
        ) % self._buffer.shape[0]
        self._buffer[write_indexes] = center

        timeline = self._sample_position + np.arange(frame_count, dtype=np.float64)
        base_frames, modulation_frames, width = _delay_components(
            self._settings,
            self._sample_rate,
        )
        left_delay = (
            base_frames * (1.0 - 0.16 * width)
            + modulation_frames
            * np.sin(2.0 * math.pi * _LEFT_RATE_HZ * timeline / self._sample_rate)
        )
        right_delay = (
            base_frames * (1.0 + 0.16 * width)
            + modulation_frames
            * np.sin(
                2.0 * math.pi * _RIGHT_RATE_HZ * timeline / self._sample_rate
                + math.pi * width
            )
        )
        left = self._read(write_indexes.astype(np.float64) - left_delay)
        right = self._read(write_indexes.astype(np.float64) - right_delay)
        mono = (left + right) * 0.5
        output = np.column_stack(
            (
                mono * (1.0 - width) + left * width,
                mono * (1.0 - width) + right * width,
            )
        ).astype(np.float32, copy=False)
        self._write_position = int((self._write_position + frame_count) % self._buffer.shape[0])
        self._sample_position += frame_count
        return output

    def _read(self, positions: np.ndarray) -> np.ndarray:
        positions = np.mod(positions, self._buffer.shape[0])
        lower = np.floor(positions).astype(np.int64)
        upper = (lower + 1) % self._buffer.shape[0]
        fraction = positions - lower
        return np.asarray(
            self._buffer[lower] * (1.0 - fraction) + self._buffer[upper] * fraction,
            dtype=np.float32,
        )


def _stereo(audio: np.ndarray) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        source = source[:, None]
    if source.ndim != 2:
        raise ValueError("Audio must be a mono or channel-based sample array.")
    if source.shape[1] == 1:
        return np.repeat(source, 2, axis=1)
    return source[:, :2]


def _ratio(percent: int) -> float:
    return max(0.0, min(1.0, float(percent) / 100.0))


def doubler_max_delay_frames(
    settings: StudioDoublerSettings,
    sample_rate: int,
) -> float:
    base_frames, modulation_frames, width = _delay_components(settings, sample_rate)
    return base_frames * (1.0 + 0.16 * width) + modulation_frames


def _delay_components(
    settings: StudioDoublerSettings,
    sample_rate: int,
) -> tuple[float, float, float]:
    rate = max(1, int(sample_rate))
    width = _ratio(settings.stereo_width_percent)
    base_frames = max(
        _PROCESS_BLOCK_FRAMES + 2,
        settings.voice_spacing_ms * rate / 1_000.0,
    )
    detune_ratio = 2.0 ** (settings.pitch_spread_cents / 1_200.0) - 1.0
    modulation_frames = min(
        base_frames * 0.42,
        detune_ratio * rate / (2.0 * math.pi * _LEFT_RATE_HZ),
    )
    return base_frames, modulation_frames, width
