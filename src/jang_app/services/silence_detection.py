from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_preview import prepare_preview_audio


@dataclass(frozen=True)
class SpeechRegion:
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def detect_speech_regions(
    source: Path,
    *,
    threshold_db: int = -40,
    min_silence_ms: int = 500,
    padding_ms: int = 120,
    frame_ms: int = 20,
    progress: Callable[[int], None] | None = None,
) -> tuple[SpeechRegion, ...]:
    preview_path = prepare_preview_audio(source)
    with sf.SoundFile(preview_path) as audio:
        sample_rate = audio.samplerate
        duration_ms = round(len(audio) / sample_rate * 1000) if sample_rate > 0 else 0
        active = _stream_active_frames(audio, frame_ms, threshold_db, progress)
    if active.size == 0 or duration_ms <= 0:
        return ()

    max_gap_frames = max(0, round(max(0, min_silence_ms) / frame_ms))
    active = _fill_short_silent_gaps(active, max_gap_frames)
    regions = _active_regions(active, frame_ms, duration_ms)
    padded = (
        SpeechRegion(
            max(0, region.start_ms - max(0, padding_ms)),
            min(duration_ms, region.end_ms + max(0, padding_ms)),
        )
        for region in regions
    )
    return _merge_regions(tuple(region for region in padded if region.duration_ms >= 100))


def _stream_active_frames(
    audio: sf.SoundFile,
    frame_ms: int,
    threshold_db: int,
    progress: Callable[[int], None] | None,
) -> np.ndarray:
    if audio.samplerate <= 0 or len(audio) <= 0:
        return np.array([], dtype=bool)
    frame_size = max(1, round(audio.samplerate * frame_ms / 1000))
    block_size = frame_size * 2048
    threshold = max(-100, min(0, threshold_db))
    active_blocks: list[np.ndarray] = []
    processed = 0
    while True:
        block = audio.read(block_size, always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1)
        remainder = len(mono) % frame_size
        if remainder:
            mono = np.pad(mono, (0, frame_size - remainder))
        frames = mono.reshape(-1, frame_size)
        rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
        active_blocks.append(20 * np.log10(np.maximum(rms, 1e-9)) >= threshold)
        processed += len(block)
        if progress is not None:
            progress(max(0, min(100, round(processed * 100 / len(audio)))))
    if progress is not None:
        progress(100)
    return np.concatenate(active_blocks) if active_blocks else np.array([], dtype=bool)


def _fill_short_silent_gaps(active: np.ndarray, max_gap_frames: int) -> np.ndarray:
    filled = active.copy()
    if max_gap_frames <= 0:
        return filled
    index = 0
    while index < len(filled):
        if filled[index]:
            index += 1
            continue
        start = index
        while index < len(filled) and not filled[index]:
            index += 1
        gap_length = index - start
        has_active_before = start > 0 and filled[start - 1]
        has_active_after = index < len(filled) and filled[index]
        if has_active_before and has_active_after and gap_length < max_gap_frames:
            filled[start:index] = True
    return filled


def _active_regions(active: np.ndarray, frame_ms: int, duration_ms: int) -> tuple[SpeechRegion, ...]:
    regions: list[SpeechRegion] = []
    index = 0
    while index < len(active):
        if not active[index]:
            index += 1
            continue
        start = index
        while index < len(active) and active[index]:
            index += 1
        regions.append(SpeechRegion(start * frame_ms, min(duration_ms, index * frame_ms)))
    return tuple(regions)


def _merge_regions(regions: tuple[SpeechRegion, ...]) -> tuple[SpeechRegion, ...]:
    merged: list[SpeechRegion] = []
    for region in sorted(regions, key=lambda item: item.start_ms):
        if not merged or region.start_ms > merged[-1].end_ms:
            merged.append(region)
            continue
        previous = merged[-1]
        merged[-1] = SpeechRegion(previous.start_ms, max(previous.end_ms, region.end_ms))
    return tuple(merged)
