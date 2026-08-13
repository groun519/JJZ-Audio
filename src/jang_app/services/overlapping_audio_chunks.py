from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class OverlappingAudioChunk:
    index: int
    core_start_frame: int
    core_end_frame: int
    source_start_frame: int
    source_end_frame: int
    source_sample_rate: int
    path: Path

    @property
    def source_frame_count(self) -> int:
        return self.source_end_frame - self.source_start_frame


def audio_requires_chunking(
    source: Path,
    *,
    duration_threshold_seconds: float,
    size_threshold_bytes: int,
) -> bool:
    try:
        info = sf.info(source)
        duration_seconds = info.frames / max(1, info.samplerate)
        return (
            duration_seconds > duration_threshold_seconds
            or source.stat().st_size > size_threshold_bytes
        )
    except (OSError, RuntimeError, ValueError):
        return False


def write_overlapping_audio_chunks(
    source: Path,
    output_dir: Path,
    *,
    core_seconds: float,
    context_seconds: float,
    boundary_search_seconds: float = 0.0,
    consistent_peak_target: float | None = None,
) -> tuple[OverlappingAudioChunk, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[OverlappingAudioChunk] = []
    with sf.SoundFile(source) as stream:
        sample_rate = stream.samplerate
        gain = _global_downmix_peak_gain(stream, consistent_peak_target)
        core_frames = max(1, round(core_seconds * sample_rate))
        context_frames = max(0, round(context_seconds * sample_rate))
        search_frames = max(0, round(boundary_search_seconds * sample_rate))
        core_ranges = _low_energy_core_ranges(stream, core_frames, search_frames)
        for index, (core_start, core_end) in enumerate(core_ranges):
            source_start = max(0, core_start - context_frames)
            source_end = min(stream.frames, core_end + context_frames)
            stream.seek(source_start)
            audio = stream.read(
                source_end - source_start,
                dtype="float32",
                always_2d=True,
            )
            if gain != 1.0:
                audio *= gain
            chunk_path = output_dir / f"c{index:03d}_i.wav"
            sf.write(chunk_path, audio, sample_rate, subtype="FLOAT")
            chunks.append(
                OverlappingAudioChunk(
                    index=index,
                    core_start_frame=core_start,
                    core_end_frame=core_end,
                    source_start_frame=source_start,
                    source_end_frame=source_end,
                    source_sample_rate=sample_rate,
                    path=chunk_path,
                )
            )
    return tuple(chunks)


def _global_downmix_peak_gain(
    stream: sf.SoundFile,
    target_peak: float | None,
) -> float:
    if target_peak is None or not 0.0 < target_peak <= 1.0:
        stream.seek(0)
        return 1.0

    peak = 0.0
    stream.seek(0)
    while True:
        audio = stream.read(1_048_576, dtype="float32", always_2d=True)
        if not len(audio):
            break
        downmix = np.mean(audio, axis=1)
        peak = max(peak, float(np.max(np.abs(downmix), initial=0.0)))
    stream.seek(0)
    return target_peak / peak if peak > target_peak else 1.0


def stitch_crossfaded_audio_chunks(
    chunks: Sequence[OverlappingAudioChunk],
    converted_paths: Sequence[Path],
    output_path: Path,
    *,
    transition_seconds: float = 0.1,
) -> Path:
    if not chunks or len(chunks) != len(converted_paths):
        raise ValueError("Audio chunks and converted outputs must have the same non-zero length")

    first_info = sf.info(converted_paths[0])
    sample_rate = first_info.samplerate
    channels = first_info.channels
    subtype = first_info.subtype if first_info.subtype.startswith("PCM_") else "PCM_16"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pending: np.ndarray | None = None
    pending_end_frame = 0
    with sf.SoundFile(
        output_path,
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        format="WAV",
        subtype=subtype,
    ) as output:
        for position, (chunk, converted_path) in enumerate(
            zip(chunks, converted_paths, strict=True)
        ):
            audio = _read_normalized_chunk(
                converted_path,
                chunk,
                sample_rate=sample_rate,
                channels=channels,
            )
            transition_source_frames = max(
                0,
                round(transition_seconds * chunk.source_sample_rate),
            )
            transition_before = transition_source_frames // 2 if position > 0 else 0
            transition_after = (
                transition_source_frames - transition_source_frames // 2
                if position + 1 < len(chunks)
                else 0
            )
            piece_start_source = max(
                chunk.source_start_frame,
                chunk.core_start_frame - transition_before,
            )
            piece_end_source = min(
                chunk.source_end_frame,
                chunk.core_end_frame + transition_after,
            )
            ratio = sample_rate / max(1, chunk.source_sample_rate)
            local_start = round(
                (piece_start_source - chunk.source_start_frame) * ratio
            )
            local_end = round(
                (piece_end_source - chunk.source_start_frame) * ratio
            )
            audio = audio[local_start:local_end]
            piece_start_frame = round(piece_start_source * ratio)
            piece_end_frame = round(piece_end_source * ratio)
            if pending is None:
                pending = audio
                pending_end_frame = piece_end_frame
                continue

            overlap_frames = max(0, pending_end_frame - piece_start_frame)
            overlap_frames = min(overlap_frames, len(pending), len(audio))
            if overlap_frames <= 0:
                output.write(pending)
                pending = audio
            else:
                output.write(pending[:-overlap_frames])
                output.write(
                    _power_preserving_crossfade(
                        pending[-overlap_frames:],
                        audio[:overlap_frames],
                    )
                )
                pending = audio[overlap_frames:]
            pending_end_frame = piece_end_frame

        if pending is not None:
            output.write(pending)
    return output_path


def _low_energy_core_ranges(
    stream: sf.SoundFile,
    core_frames: int,
    search_frames: int,
) -> tuple[tuple[int, int], ...]:
    if stream.frames <= core_frames:
        stream.seek(0)
        return ((0, stream.frames),)

    boundaries = [0]
    while boundaries[-1] + core_frames < stream.frames:
        target = boundaries[-1] + core_frames
        if stream.frames - target < core_frames // 2:
            break
        if search_frames <= 0:
            boundary = target
        else:
            search_start = max(boundaries[-1] + core_frames // 2, target - search_frames)
            search_end = min(
                stream.frames - core_frames // 2,
                target + search_frames,
            )
            boundary = _lowest_energy_frame(stream, search_start, search_end, target)
        if boundary <= boundaries[-1] or boundary >= stream.frames:
            break
        boundaries.append(boundary)
    boundaries.append(stream.frames)
    stream.seek(0)
    return tuple(zip(boundaries, boundaries[1:]))


def _lowest_energy_frame(
    stream: sf.SoundFile,
    start_frame: int,
    end_frame: int,
    fallback_frame: int,
) -> int:
    if end_frame <= start_frame:
        return fallback_frame
    stream.seek(start_frame)
    audio = stream.read(end_frame - start_frame, dtype="float32", always_2d=True)
    if not len(audio):
        return fallback_frame
    mono = np.mean(audio, axis=1)
    window_frames = max(1, round(stream.samplerate * 0.05))
    remainder = len(mono) % window_frames
    if remainder:
        mono = np.pad(mono, (0, window_frames - remainder))
    windows = mono.reshape(-1, window_frames)
    rms = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
    index = int(np.argmin(rms))
    return min(end_frame, start_frame + index * window_frames + window_frames // 2)


def _power_preserving_crossfade(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    frame_count = min(len(left), len(right))
    if frame_count <= 0:
        return np.empty((0, left.shape[1]), dtype=np.float32)
    left = left[:frame_count]
    right = right[:frame_count]
    denominator = float(
        np.sqrt(
            np.sum(np.square(left, dtype=np.float64))
            * np.sum(np.square(right, dtype=np.float64))
        )
    )
    correlation = (
        float(np.sum(left.astype(np.float64) * right.astype(np.float64))) / denominator
        if denominator > 1e-12
        else 1.0
    )
    correlation = max(0.0, min(1.0, correlation))
    fade_in = np.linspace(0.0, 1.0, frame_count, endpoint=True, dtype=np.float32)
    fade_out = 1.0 - fade_in
    normalization = np.sqrt(
        np.square(fade_out)
        + np.square(fade_in)
        + 2.0 * correlation * fade_out * fade_in
    )
    normalization = np.maximum(normalization, 1e-6)[:, np.newaxis]
    return (left * fade_out[:, np.newaxis] + right * fade_in[:, np.newaxis]) / normalization


def _read_normalized_chunk(
    path: Path,
    chunk: OverlappingAudioChunk,
    *,
    sample_rate: int,
    channels: int,
) -> np.ndarray:
    info = sf.info(path)
    if info.samplerate != sample_rate or info.channels != channels:
        raise ValueError("Converted audio chunks must use a consistent sample rate and channel count")
    audio, _ = sf.read(path, dtype="float32", always_2d=True)
    expected_frames = round(
        chunk.source_frame_count
        * sample_rate
        / max(1, chunk.source_sample_rate)
    )
    if len(audio) > expected_frames:
        return audio[:expected_frames]
    if len(audio) < expected_frames:
        return np.pad(audio, ((0, expected_frames - len(audio)), (0, 0)))
    return audio
