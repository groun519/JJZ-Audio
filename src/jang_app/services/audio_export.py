from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf


class AudioExportError(RuntimeError):
    """Raised when preview audio cannot be exported."""


NamedAudioPath = tuple[str, Path]


@dataclass(frozen=True)
class AudioMixSource:
    label: str
    path: Path
    volume: float = 1.0


def export_mix(sources: Sequence[AudioMixSource], output_path: Path) -> Path:
    if not sources:
        raise AudioExportError("Select at least one unmuted track before exporting a mix.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_arrays: list[np.ndarray] = []
    sample_rate: int | None = None
    max_frames = 0
    max_channels = 0

    for source in sources:
        audio, current_sample_rate = _read_audio(source.path)
        if sample_rate is None:
            sample_rate = current_sample_rate
        else:
            audio = _resample_audio(audio, current_sample_rate, sample_rate)

        audio_arrays.append(audio * _clamp_volume(source.volume))
        max_frames = max(max_frames, audio.shape[0])
        max_channels = max(max_channels, audio.shape[1])

    mix = np.zeros((max_frames, max_channels), dtype=np.float32)
    for audio in audio_arrays:
        mix[: audio.shape[0], :] += _match_channels(audio, max_channels)

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 1.0:
        mix /= peak

    sf.write(output_path, mix, sample_rate or 44100, subtype="PCM_16")
    return output_path


def export_audio_files(sources: Sequence[NamedAudioPath], output_dir: Path) -> list[Path]:
    if not sources:
        raise AudioExportError("No tracks are loaded to export.")

    output_dir.mkdir(parents=True, exist_ok=True)
    exported_paths: list[Path] = []
    for label, source in sources:
        target = output_dir / f"{_slugify(label)}{source.suffix.lower() or '.wav'}"
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


def _clamp_volume(volume: float) -> float:
    return max(0.0, min(2.0, volume))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "audio"
