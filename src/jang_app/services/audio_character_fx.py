from __future__ import annotations

import math

import numpy as np

from jang_app.services.studio_character_fx_presets import CHARACTER_EFFECT_KINDS
from jang_app.services.studio_session import (
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DISTORTION,
    STUDIO_EFFECT_RADIO_FILTER,
    STUDIO_EFFECT_RING_MODULATOR,
    StudioEffect,
)


class CharacterEffectProcessor:
    """Stateful processor shared by live playback and offline rendering."""

    def __init__(self, sample_rate: int, effect: StudioEffect) -> None:
        if effect.kind not in CHARACTER_EFFECT_KINDS:
            raise ValueError(f"Unsupported character effect: {effect.kind}")
        self._sample_rate = max(1, int(sample_rate))
        self._effect = effect
        self._phase = 0.0
        self._hold_offset = 0
        self._held_sample: np.ndarray | None = None
        self._filter_kernel = np.ones(1, dtype=np.float32)
        self._filter_history: np.ndarray | None = None
        self.update(effect)

    @property
    def kind(self) -> str:
        return self._effect.kind

    def update(self, effect: StudioEffect) -> None:
        if effect.kind != self._effect.kind:
            raise ValueError("An effect processor cannot change effect kind.")
        filter_changed = effect.radio_filter != self._effect.radio_filter
        self._effect = effect
        if effect.kind == STUDIO_EFFECT_RADIO_FILTER and (
            filter_changed or self._filter_kernel.size == 1
        ):
            self._filter_kernel = _bandpass_kernel(
                self._sample_rate,
                effect.radio_filter.low_cut_hz,
                effect.radio_filter.high_cut_hz,
            )
            self._filter_history = None

    def process(self, audio: np.ndarray) -> np.ndarray:
        source, was_mono = _audio_matrix(audio)
        if source.shape[0] == 0:
            return _restore_shape(source.copy(), was_mono)
        if self._effect.kind == STUDIO_EFFECT_RADIO_FILTER:
            processed = self._process_radio_filter(source)
        elif self._effect.kind == STUDIO_EFFECT_RING_MODULATOR:
            processed = self._process_ring_modulator(source)
        elif self._effect.kind == STUDIO_EFFECT_BITCRUSHER:
            processed = self._process_bitcrusher(source)
        else:
            processed = self._process_distortion(source)
        return _restore_shape(np.asarray(processed, dtype=np.float32), was_mono)

    def _process_radio_filter(self, source: np.ndarray) -> np.ndarray:
        history_frames = self._filter_kernel.size - 1
        if self._filter_history is None or self._filter_history.shape[1] != source.shape[1]:
            self._filter_history = np.zeros(
                (history_frames, source.shape[1]),
                dtype=np.float32,
            )
        combined = np.concatenate((self._filter_history, source), axis=0)
        wet = np.empty_like(source)
        for channel in range(source.shape[1]):
            filtered = np.convolve(
                combined[:, channel],
                self._filter_kernel,
                mode="full",
            )
            wet[:, channel] = filtered[history_frames : history_frames + source.shape[0]]
        if history_frames:
            self._filter_history = combined[-history_frames:].copy()
        return _mix(source, wet, self._effect.radio_filter.mix_percent)

    def _process_ring_modulator(self, source: np.ndarray) -> np.ndarray:
        frequency = self._effect.ring_modulator.frequency_hz
        step = 2.0 * math.pi * frequency / self._sample_rate
        phase = self._phase + step * np.arange(source.shape[0], dtype=np.float64)
        carrier = np.sin(phase).astype(np.float32)[:, None]
        self._phase = float((self._phase + step * source.shape[0]) % (2.0 * math.pi))
        return _mix(
            source,
            source * carrier,
            self._effect.ring_modulator.mix_percent,
        )

    def _process_bitcrusher(self, source: np.ndarray) -> np.ndarray:
        settings = self._effect.bitcrusher
        hold_frames = max(1, round(self._sample_rate / settings.sample_rate_hz))
        positions = (self._hold_offset + np.arange(source.shape[0])) % hold_frames
        update_mask = positions == 0
        if self._held_sample is None or self._held_sample.shape[0] != source.shape[1]:
            self._held_sample = source[0].copy()
            update_mask[0] = True
        source_indexes = np.where(update_mask, np.arange(source.shape[0]), -1)
        last_indexes = np.maximum.accumulate(source_indexes)
        held = np.empty_like(source)
        before_first = last_indexes < 0
        held[before_first] = self._held_sample
        if np.any(~before_first):
            held[~before_first] = source[last_indexes[~before_first]]
        self._held_sample = held[-1].copy()
        self._hold_offset = int((self._hold_offset + source.shape[0]) % hold_frames)
        levels = float((1 << (settings.bit_depth - 1)) - 1)
        crushed = np.round(np.clip(held, -1.0, 1.0) * levels) / levels
        return _mix(source, crushed, settings.mix_percent)

    def _process_distortion(self, source: np.ndarray) -> np.ndarray:
        settings = self._effect.distortion
        drive = 1.0 + 19.0 * settings.drive_percent / 100.0
        distorted = np.tanh(source * drive) / math.tanh(drive)
        return _mix(source, distorted, settings.mix_percent)


def create_character_effect_processor(
    sample_rate: int,
    effect: StudioEffect,
) -> CharacterEffectProcessor:
    return CharacterEffectProcessor(sample_rate, effect)


def apply_character_effect(
    audio: np.ndarray,
    sample_rate: int,
    effect: StudioEffect,
) -> np.ndarray:
    return CharacterEffectProcessor(sample_rate, effect).process(audio)


def _audio_matrix(audio: np.ndarray) -> tuple[np.ndarray, bool]:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        return source[:, None], True
    if source.ndim != 2:
        raise ValueError("Audio must be a mono or channel-based sample array.")
    return source, False


def _restore_shape(audio: np.ndarray, was_mono: bool) -> np.ndarray:
    return audio[:, 0] if was_mono else audio


def _mix(dry: np.ndarray, wet: np.ndarray, mix_percent: int) -> np.ndarray:
    mix = max(0.0, min(1.0, int(mix_percent) / 100.0))
    if mix <= 0.0:
        return dry.copy()
    if mix >= 1.0:
        return np.asarray(wet, dtype=np.float32)
    return np.asarray(dry * (1.0 - mix) + wet * mix, dtype=np.float32)


def _bandpass_kernel(
    sample_rate: int,
    low_cut_hz: int,
    high_cut_hz: int,
    taps: int = 63,
) -> np.ndarray:
    nyquist = sample_rate / 2.0
    low = max(20.0, min(float(low_cut_hz), nyquist * 0.85))
    high = max(low + 100.0, min(float(high_cut_hz), nyquist * 0.98))
    if high >= nyquist:
        high = nyquist * 0.98
    indexes = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    high_pass = 2.0 * high / sample_rate * np.sinc(2.0 * high * indexes / sample_rate)
    low_pass = 2.0 * low / sample_rate * np.sinc(2.0 * low * indexes / sample_rate)
    kernel = (high_pass - low_pass) * np.hamming(taps)
    center = math.sqrt(low * high)
    response = abs(np.sum(kernel * np.exp(-2j * math.pi * center * indexes / sample_rate)))
    if response > 1e-8:
        kernel /= response
    return np.asarray(kernel, dtype=np.float32)
