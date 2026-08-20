from __future__ import annotations

import math

import numpy as np

from jang_app.services.pitch_profile import estimate_pitch_midi
from jang_app.services.studio_session import StudioHardTuneSettings


HARD_TUNE_SCALES = {
    "chromatic": tuple(range(12)),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
}

_PROCESS_BLOCK_FRAMES = 1_024
_ANALYSIS_MS = 90
_MIN_DELAY_MS = 4
_DELAY_SPAN_MS = 20
_SILENCE_FLOOR = 10.0 ** (-55.0 / 20.0)


def quantized_pitch_midi(pitch_midi: float, key_note: int, scale: str) -> float:
    """Return the nearest MIDI note allowed by the selected key and scale."""
    allowed = HARD_TUNE_SCALES.get(scale, HARD_TUNE_SCALES["chromatic"])
    root = int(key_note) % 12
    center = int(round(pitch_midi))
    candidates = (
        note
        for note in range(center - 12, center + 13)
        if (note - root) % 12 in allowed
    )
    return float(min(candidates, key=lambda note: (abs(note - pitch_midi), note)))


class HardTuneProcessor:
    """Stateful monophonic pitch quantizer shared by preview and export."""

    def __init__(self, sample_rate: int, settings: StudioHardTuneSettings) -> None:
        self._sample_rate = max(1, int(sample_rate))
        self._analysis_frames = max(
            _PROCESS_BLOCK_FRAMES * 2,
            round(self._sample_rate * _ANALYSIS_MS / 1_000),
        )
        self._min_delay_frames = max(
            1,
            round(self._sample_rate * _MIN_DELAY_MS / 1_000),
        )
        self._delay_span_frames = max(
            2,
            round(self._sample_rate * _DELAY_SPAN_MS / 1_000),
        )
        self._history_frames = (
            self._min_delay_frames + self._delay_span_frames + 2
        )
        self._analysis_history = np.zeros(0, dtype=np.float32)
        self._delay_history: np.ndarray | None = None
        self._phase = 0.25
        self._current_shift = 0.0
        self._settings = settings

    def update(self, settings: StudioHardTuneSettings) -> None:
        self._settings = settings

    def process(self, audio: np.ndarray) -> np.ndarray:
        source, was_mono = _audio_matrix(audio)
        if source.shape[0] == 0:
            return _restore_shape(source.copy(), was_mono)
        processed = np.empty_like(source)
        for start in range(0, source.shape[0], _PROCESS_BLOCK_FRAMES):
            end = min(source.shape[0], start + _PROCESS_BLOCK_FRAMES)
            processed[start:end] = self._process_block(source[start:end])
        return _restore_shape(processed, was_mono)

    def _process_block(self, source: np.ndarray) -> np.ndarray:
        mono = np.mean(source, axis=1, dtype=np.float32)
        analysis = np.concatenate((self._analysis_history, mono))
        if analysis.size > self._analysis_frames:
            analysis = analysis[-self._analysis_frames :]
        self._analysis_history = analysis.copy()

        target_shift = self._target_shift(analysis)
        response_seconds = max(0.005, self._settings.response_ms / 1_000.0)
        block_seconds = source.shape[0] / self._sample_rate
        smoothing = 1.0 - math.exp(-block_seconds / response_seconds)
        self._current_shift += (target_shift - self._current_shift) * smoothing
        return self._shift_block(source, self._current_shift)

    def _target_shift(self, analysis: np.ndarray) -> float:
        if analysis.size < _PROCESS_BLOCK_FRAMES * 2:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(analysis, dtype=np.float64))))
        if rms < _SILENCE_FLOOR:
            return 0.0
        pitch = estimate_pitch_midi(analysis, self._sample_rate)
        if pitch is None:
            return 0.0
        target = quantized_pitch_midi(
            pitch,
            self._settings.key_note,
            self._settings.scale,
        )
        correction = target - pitch
        strength = self._settings.strength_percent / 100.0
        vibrato_reduction = 1.0 - self._settings.vibrato_preserve_percent / 100.0
        return correction * strength * vibrato_reduction

    def _shift_block(self, source: np.ndarray, semitones: float) -> np.ndarray:
        if self._delay_history is None or self._delay_history.shape[1] != source.shape[1]:
            self._delay_history = np.zeros(
                (self._history_frames, source.shape[1]),
                dtype=np.float32,
            )
        combined = np.concatenate((self._delay_history, source), axis=0)
        self._delay_history = combined[-self._history_frames :].copy()
        if abs(semitones) < 0.001:
            return source.copy()

        ratio = 2.0 ** (semitones / 12.0)
        phase_step = (1.0 - ratio) / self._delay_span_frames
        offsets = np.arange(source.shape[0], dtype=np.float64)
        phase_a = np.mod(self._phase + phase_step * offsets, 1.0)
        phase_b = np.mod(phase_a + 0.5, 1.0)
        self._phase = float(
            (self._phase + phase_step * source.shape[0]) % 1.0
        )

        wet_a = self._read_delay(combined, phase_a)
        wet_b = self._read_delay(combined, phase_b)
        weight_a = np.square(np.sin(math.pi * phase_a))[:, None]
        weight_b = np.square(np.sin(math.pi * phase_b))[:, None]
        wet = np.asarray(wet_a * weight_a + wet_b * weight_b, dtype=np.float32)
        wet_mix = min(1.0, abs(semitones) / 0.08)
        return np.asarray(source * (1.0 - wet_mix) + wet * wet_mix, dtype=np.float32)

    def _read_delay(self, audio: np.ndarray, phase: np.ndarray) -> np.ndarray:
        delays = self._min_delay_frames + phase * self._delay_span_frames
        positions = self._history_frames + np.arange(phase.size) - delays
        lower = np.floor(positions).astype(np.int64)
        fraction = (positions - lower)[:, None]
        upper = np.minimum(lower + 1, audio.shape[0] - 1)
        return audio[lower] * (1.0 - fraction) + audio[upper] * fraction


def apply_hard_tune(
    audio: np.ndarray,
    sample_rate: int,
    settings: StudioHardTuneSettings,
) -> np.ndarray:
    return HardTuneProcessor(sample_rate, settings).process(audio)


def _audio_matrix(audio: np.ndarray) -> tuple[np.ndarray, bool]:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        return source[:, None], True
    if source.ndim != 2:
        raise ValueError("Audio must be a mono or channel-based sample array.")
    return source, False


def _restore_shape(audio: np.ndarray, was_mono: bool) -> np.ndarray:
    return audio[:, 0] if was_mono else audio
