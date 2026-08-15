from __future__ import annotations

import numpy as np

from jang_app.services.studio_session import StudioDelaySettings


_PROCESS_BLOCK_FRAMES = 128


class RealtimeDelay:
    """Low-latency stereo delay with persistent feedback state."""

    def __init__(self, sample_rate: int, settings: StudioDelaySettings) -> None:
        self._sample_rate = max(1, int(sample_rate))
        self._settings = settings
        self._line = _StereoDelayLine(*self._delay_frames(settings))

    def update(self, settings: StudioDelaySettings) -> None:
        frames = self._delay_frames(settings)
        if frames != self._line.frame_counts:
            self._line = _StereoDelayLine(*frames)
        self._settings = settings

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = _stereo(audio)
        if source.shape[0] == 0:
            return source
        output = np.empty_like(source)
        feedback = _ratio(self._settings.feedback_percent, maximum=0.85)
        wet_mix = _ratio(self._settings.dry_wet_percent)
        for start in range(0, source.shape[0], _PROCESS_BLOCK_FRAMES):
            end = min(source.shape[0], start + _PROCESS_BLOCK_FRAMES)
            block = source[start:end]
            delayed = self._line.process(block, feedback)
            output[start:end] = block * (1.0 - wet_mix) + delayed * wet_mix
        return np.clip(output, -8.0, 8.0).astype(np.float32, copy=False)

    def _delay_frames(self, settings: StudioDelaySettings) -> tuple[int, int]:
        base = max(
            _PROCESS_BLOCK_FRAMES + 1,
            round(settings.delay_ms * self._sample_rate / 1_000.0),
        )
        width = _ratio(settings.stereo_width_percent)
        right = max(base, round(base * (1.0 + 0.24 * width)))
        return base, right


class _StereoDelayLine:
    def __init__(self, left_frames: int, right_frames: int) -> None:
        self._buffers = (
            np.zeros(max(_PROCESS_BLOCK_FRAMES + 1, left_frames), dtype=np.float32),
            np.zeros(max(_PROCESS_BLOCK_FRAMES + 1, right_frames), dtype=np.float32),
        )
        self._positions = [0, 0]

    @property
    def frame_counts(self) -> tuple[int, int]:
        return self._buffers[0].shape[0], self._buffers[1].shape[0]

    def process(self, source: np.ndarray, feedback: float) -> np.ndarray:
        delayed = np.empty_like(source)
        frame_count = source.shape[0]
        for channel, buffer in enumerate(self._buffers):
            position = self._positions[channel]
            indices = (np.arange(frame_count) + position) % buffer.shape[0]
            channel_delay = buffer[indices].copy()
            delayed[:, channel] = channel_delay
            buffer[indices] = source[:, channel] + channel_delay * feedback
            self._positions[channel] = (position + frame_count) % buffer.shape[0]
        return delayed


def _stereo(audio: np.ndarray) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        source = source[:, None]
    if source.shape[1] == 1:
        return np.repeat(source, 2, axis=1)
    return source[:, :2]


def _ratio(percent: int, *, maximum: float = 1.0) -> float:
    return max(0.0, min(maximum, float(percent) / 100.0))
