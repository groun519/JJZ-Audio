from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class OverlappingAudioChunk:
    index: int
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
) -> tuple[OverlappingAudioChunk, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[OverlappingAudioChunk] = []
    with sf.SoundFile(source) as stream:
        sample_rate = stream.samplerate
        core_frames = max(1, round(core_seconds * sample_rate))
        context_frames = max(0, round(context_seconds * sample_rate))
        core_start = 0
        index = 0
        while core_start < stream.frames:
            core_end = min(stream.frames, core_start + core_frames)
            source_start = max(0, core_start - context_frames)
            source_end = min(stream.frames, core_end + context_frames)
            stream.seek(source_start)
            audio = stream.read(
                source_end - source_start,
                dtype="float32",
                always_2d=True,
            )
            chunk_path = output_dir / f"c{index:03d}_i.wav"
            sf.write(chunk_path, audio, sample_rate, subtype="FLOAT")
            chunks.append(
                OverlappingAudioChunk(
                    index=index,
                    source_start_frame=source_start,
                    source_end_frame=source_end,
                    source_sample_rate=sample_rate,
                    path=chunk_path,
                )
            )
            core_start = core_end
            index += 1
    return tuple(chunks)


def stitch_crossfaded_audio_chunks(
    chunks: Sequence[OverlappingAudioChunk],
    converted_paths: Sequence[Path],
    output_path: Path,
) -> Path:
    if not chunks or len(chunks) != len(converted_paths):
        raise ValueError("Audio chunks and converted outputs must have the same non-zero length")

    first_info = sf.info(converted_paths[0])
    sample_rate = first_info.samplerate
    channels = first_info.channels
    subtype = first_info.subtype if first_info.subtype.startswith("PCM_") else "PCM_16"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pending: np.ndarray | None = None
    previous_chunk: OverlappingAudioChunk | None = None
    with sf.SoundFile(
        output_path,
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        format="WAV",
        subtype=subtype,
    ) as output:
        for chunk, converted_path in zip(chunks, converted_paths, strict=True):
            audio = _read_normalized_chunk(
                converted_path,
                chunk,
                sample_rate=sample_rate,
                channels=channels,
            )
            if pending is None:
                pending = audio
                previous_chunk = chunk
                continue

            overlap_source_frames = max(
                0,
                previous_chunk.source_end_frame - chunk.source_start_frame,
            )
            overlap_frames = round(
                overlap_source_frames
                * sample_rate
                / max(1, chunk.source_sample_rate)
            )
            overlap_frames = min(overlap_frames, len(pending), len(audio))
            if overlap_frames <= 0:
                output.write(pending)
                pending = audio
            else:
                output.write(pending[:-overlap_frames])
                fade_in = np.linspace(
                    0.0,
                    1.0,
                    overlap_frames,
                    endpoint=True,
                    dtype=np.float32,
                )[:, np.newaxis]
                output.write(
                    pending[-overlap_frames:] * (1.0 - fade_in)
                    + audio[:overlap_frames] * fade_in
                )
                pending = audio[overlap_frames:]
            previous_chunk = chunk

        if pending is not None:
            output.write(pending)
    return output_path


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
