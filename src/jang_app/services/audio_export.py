from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.file_names import safe_display_filename_stem, unique_display_path
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.studio_session import StudioEffect


class AudioExportError(RuntimeError):
    """Raised when audio cannot be rendered or exported."""


NamedAudioPath = tuple[str, Path]


@dataclass(frozen=True)
class AudioMixSource:
    label: str
    path: Path
    volume: float = 1.0
    timeline_start_ms: int = 0
    source_start_ms: int = 0
    source_end_ms: int | None = None
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    pan_percent: int = 0
    effects: tuple[StudioEffect, ...] = ()
    reference_path: Path | None = None


@dataclass(frozen=True)
class RenderedAudioMix:
    samples: np.ndarray
    sample_rate: int


def export_mix(
    sources: Sequence[AudioMixSource],
    output_path: Path,
) -> Path:
    rendered = render_audio_mix(sources)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(
        output_path,
        np.clip(rendered.samples, -1.0, 1.0),
        rendered.sample_rate,
        subtype="PCM_16",
    )
    return output_path


def render_audio_mix(sources: Sequence[AudioMixSource]) -> RenderedAudioMix:
    if not sources:
        raise AudioExportError("Select at least one unmuted track before exporting a mix.")

    audio_arrays: list[tuple[int, np.ndarray]] = []
    sample_rate: int | None = None
    max_frames = 0
    max_channels = 0

    for source in sources:
        audio, current_sample_rate = _read_audio(source.path)
        if sample_rate is None:
            sample_rate = current_sample_rate
        else:
            audio = _resample_audio(audio, current_sample_rate, sample_rate)

        source_start_frame = max(0, round(source.source_start_ms * sample_rate / 1000))
        source_end_frame = (
            audio.shape[0]
            if source.source_end_ms is None
            else max(0, round(source.source_end_ms * sample_rate / 1000))
        )
        trimmed = audio[source_start_frame : min(source_end_frame, audio.shape[0])]
        if trimmed.shape[0] <= 0:
            continue
        timeline_start_frame = max(0, round(source.timeline_start_ms * sample_rate / 1000))
        reference_audio = _read_reference_segment(
            source,
            sample_rate,
            source_start_frame,
            source_end_frame,
        )
        processed = process_mix_source(
            trimmed,
            sample_rate,
            volume=source.volume,
            fade_in_ms=source.fade_in_ms,
            fade_out_ms=source.fade_out_ms,
            pan_percent=source.pan_percent,
            effects=source.effects,
            reference_audio=reference_audio,
        )
        audio_arrays.append((timeline_start_frame, processed))
        max_frames = max(max_frames, timeline_start_frame + processed.shape[0])
        max_channels = max(max_channels, processed.shape[1])

    if not audio_arrays:
        raise AudioExportError("The Studio timeline does not contain playable clips.")
    mix = np.zeros((max_frames, max_channels), dtype=np.float32)
    for timeline_start_frame, audio in audio_arrays:
        timeline_end_frame = timeline_start_frame + audio.shape[0]
        mix[timeline_start_frame:timeline_end_frame, :] += _match_channels(audio, max_channels)
    return RenderedAudioMix(mix, sample_rate or 44_100)


def export_audio_files(sources: Sequence[NamedAudioPath], output_dir: Path) -> list[Path]:
    if not sources:
        raise AudioExportError("No tracks are loaded to export.")

    output_dir.mkdir(parents=True, exist_ok=True)
    exported_paths: list[Path] = []
    for label, source in sources:
        stem = safe_display_filename_stem(label, fallback="Audio")
        target = unique_display_path(
            output_dir / f"{stem}{source.suffix.lower() or '.wav'}"
        )
        if source.expanduser().resolve() != target.expanduser().resolve():
            shutil.copy2(source, target)
        exported_paths.append(target)
    return exported_paths


def export_audio_file(label: str, source: Path, output_dir: Path) -> Path:
    return export_audio_files([(label, source)], output_dir)[0]


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise AudioExportError(f"Audio file does not exist: {source}")
    audio, sample_rate = sf.read(source, always_2d=True, dtype="float32")
    return audio, sample_rate


def _read_reference_segment(
    source: AudioMixSource,
    sample_rate: int,
    source_start_frame: int,
    source_end_frame: int,
) -> np.ndarray | None:
    if source.reference_path is None or not source.reference_path.expanduser().is_file():
        return None
    reference, reference_sample_rate = _read_audio(source.reference_path)
    reference = _resample_audio(reference, reference_sample_rate, sample_rate)
    return reference[source_start_frame : min(source_end_frame, reference.shape[0])]


def _match_channels(audio: np.ndarray, target_channels: int) -> np.ndarray:
    if audio.shape[1] == target_channels:
        return audio
    if audio.shape[1] == 1:
        return np.repeat(audio, target_channels, axis=1)

    matched = np.zeros((audio.shape[0], target_channels), dtype=np.float32)
    channels_to_copy = min(audio.shape[1], target_channels)
    matched[:, :channels_to_copy] = audio[:, :channels_to_copy]
    return matched


def _resample_audio(audio: np.ndarray, source_sample_rate: int, target_sample_rate: int) -> np.ndarray:
    if source_sample_rate == target_sample_rate:
        return audio
    if source_sample_rate <= 0 or target_sample_rate <= 0:
        raise AudioExportError("Cannot mix tracks with invalid sample rates.")
    if audio.shape[0] == 0:
        return audio

    target_frames = max(1, round(audio.shape[0] * target_sample_rate / source_sample_rate))
    if audio.shape[0] == 1:
        return np.repeat(audio, target_frames, axis=0)

    source_positions = np.arange(audio.shape[0], dtype=np.float32)
    target_positions = np.linspace(0, audio.shape[0] - 1, target_frames, dtype=np.float32)
    resampled = np.empty((target_frames, audio.shape[1]), dtype=np.float32)
    for channel in range(audio.shape[1]):
        resampled[:, channel] = np.interp(target_positions, source_positions, audio[:, channel])
    return resampled
