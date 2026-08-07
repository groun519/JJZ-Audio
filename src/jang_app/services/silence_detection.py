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


def split_regions_at_low_energy(
    source: Path,
    regions: tuple[SpeechRegion, ...],
    max_duration_ms: int,
    *,
    frame_ms: int = 20,
    search_window_ms: int = 1500,
    progress: Callable[[int], None] | None = None,
) -> tuple[tuple[int, int], ...]:
    maximum = max(100, int(max_duration_ms))
    if not regions:
        if progress is not None:
            progress(100)
        return ()
    preview_path = prepare_preview_audio(source)
    with sf.SoundFile(preview_path) as audio:
        levels = _stream_frame_levels(audio, frame_ms, progress)
    if levels.size == 0:
        return tuple((region.start_ms, region.end_ms) for region in regions)

    ranges: list[tuple[int, int]] = []
    for region in regions:
        duration = region.duration_ms
        segment_count = min(
            max(1, (duration + maximum - 1) // maximum),
            max(1, duration // 100),
        )
        if segment_count == 1:
            ranges.append((region.start_ms, region.end_ms))
            continue
        minimum_segment_ms = min(3000, max(100, round(duration / segment_count * 0.45)))
        boundaries = [region.start_ms]
        for index in range(1, segment_count):
            target_ms = region.start_ms + round(duration * index / segment_count)
            remaining_segments = segment_count - index
            earliest = boundaries[-1] + minimum_segment_ms
            latest = region.end_ms - remaining_segments * minimum_segment_ms
            search_start = max(earliest, target_ms - max(0, search_window_ms))
            search_end = min(latest, target_ms + max(0, search_window_ms))
            boundary = _lowest_energy_position(levels, frame_ms, search_start, search_end, target_ms)
            boundaries.append(boundary)
        boundaries.append(region.end_ms)
        ranges.extend(
            (start_ms, end_ms)
            for start_ms, end_ms in zip(boundaries, boundaries[1:])
            if end_ms - start_ms >= 100
        )
    if progress is not None:
        progress(100)
    return tuple(ranges)


def _stream_active_frames(
    audio: sf.SoundFile,
    frame_ms: int,
    threshold_db: int,
    progress: Callable[[int], None] | None,
) -> np.ndarray:
    threshold = max(-100, min(0, threshold_db))
    return _stream_frame_levels(audio, frame_ms, progress) >= threshold


def _stream_frame_levels(
    audio: sf.SoundFile,
    frame_ms: int,
    progress: Callable[[int], None] | None,
) -> np.ndarray:
    if audio.samplerate <= 0 or len(audio) <= 0:
        return np.array([], dtype=np.float64)
    frame_size = max(1, round(audio.samplerate * frame_ms / 1000))
    block_size = frame_size * 2048
    level_blocks: list[np.ndarray] = []
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
        level_blocks.append(20 * np.log10(np.maximum(rms, 1e-9)))
        processed += len(block)
        if progress is not None:
            progress(max(0, min(99, round(processed * 100 / len(audio)))))
    if progress is not None:
        progress(100)
    return np.concatenate(level_blocks) if level_blocks else np.array([], dtype=np.float64)


def _lowest_energy_position(
    levels: np.ndarray,
    frame_ms: int,
    start_ms: int,
    end_ms: int,
    fallback_ms: int,
) -> int:
    start_frame = max(0, min(len(levels), start_ms // frame_ms))
    end_frame = max(start_frame + 1, min(len(levels), (end_ms + frame_ms - 1) // frame_ms))
    if start_frame >= len(levels) or end_frame <= start_frame:
        return fallback_ms
    local_index = int(np.argmin(levels[start_frame:end_frame]))
    return max(start_ms, min(end_ms, (start_frame + local_index) * frame_ms))


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
