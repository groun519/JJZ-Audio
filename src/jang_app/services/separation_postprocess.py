from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


_BLOCK_FRAMES = 262_144


class SeparationPostprocessError(RuntimeError):
    """Raised when separated stems cannot be safely quality-normalized."""


@dataclass(frozen=True)
class SeparationPostprocessReport:
    sample_rate: int
    channels: int
    frames: int
    residual_rms_before: float
    residual_rms_after: float
    peak: float


def enforce_mixture_consistency(
    source_path: Path,
    vocals_path: Path,
    instrumental_path: Path,
) -> SeparationPostprocessReport:
    source = source_path.expanduser().resolve()
    vocals = vocals_path.expanduser().resolve()
    instrumental = instrumental_path.expanduser().resolve()
    try:
        vocals_info = sf.info(vocals)
        instrumental_info = sf.info(instrumental)
    except (OSError, RuntimeError) as exc:
        raise SeparationPostprocessError("Could not read separated stems.") from exc

    expected = (vocals_info.samplerate, vocals_info.channels, vocals_info.frames)
    actual_instrumental = (
        instrumental_info.samplerate,
        instrumental_info.channels,
        instrumental_info.frames,
    )
    if actual_instrumental != expected:
        raise SeparationPostprocessError(
            f"Cannot align instrumental: expected rate/channels/frames {expected}, got {actual_instrumental}."
        )

    reference_temp = vocals.parent / ".mixture-reference.tmp.wav"
    reference = _matching_reference(source, vocals_info, reference_temp)
    source_info = sf.info(reference)

    vocals_temp = vocals.with_suffix(".consistent.tmp.wav")
    instrumental_temp = instrumental.with_suffix(".consistent.tmp.wav")
    residual_energy_before = 0.0
    residual_energy_after = 0.0
    sample_count = 0
    peak = 0.0
    try:
        with (
            sf.SoundFile(reference) as source_file,
            sf.SoundFile(vocals) as vocals_file,
            sf.SoundFile(instrumental) as instrumental_file,
            sf.SoundFile(
                vocals_temp,
                mode="w",
                samplerate=source_info.samplerate,
                channels=source_info.channels,
                subtype="FLOAT",
            ) as vocals_output,
            sf.SoundFile(
                instrumental_temp,
                mode="w",
                samplerate=source_info.samplerate,
                channels=source_info.channels,
                subtype="FLOAT",
            ) as instrumental_output,
        ):
            remaining = vocals_info.frames
            while remaining > 0:
                block_frames = min(_BLOCK_FRAMES, remaining)
                mixture = source_file.read(block_frames, dtype="float32", always_2d=True)
                if len(mixture) < block_frames:
                    mixture = np.pad(
                        mixture,
                        ((0, block_frames - len(mixture)), (0, 0)),
                    )
                vocal = vocals_file.read(block_frames, dtype="float32", always_2d=True)
                backing = instrumental_file.read(block_frames, dtype="float32", always_2d=True)
                if len(vocal) != block_frames or len(backing) != block_frames:
                    raise SeparationPostprocessError("A separated stem ended before its declared length.")

                residual = mixture - vocal - backing
                corrected_vocal = vocal + residual * 0.5
                corrected_backing = backing + residual * 0.5
                residual_after = mixture - corrected_vocal - corrected_backing
                vocals_output.write(corrected_vocal)
                instrumental_output.write(corrected_backing)

                residual_energy_before += float(np.sum(np.square(residual, dtype=np.float64)))
                residual_energy_after += float(np.sum(np.square(residual_after, dtype=np.float64)))
                sample_count += residual.size
                peak = max(
                    peak,
                    float(np.max(np.abs(corrected_vocal))),
                    float(np.max(np.abs(corrected_backing))),
                )
                remaining -= block_frames

        replace_stem_pair(vocals_temp, vocals, instrumental_temp, instrumental)
    finally:
        for temporary in (vocals_temp, instrumental_temp):
            if temporary.exists():
                temporary.unlink()
        if reference == reference_temp and reference_temp.exists():
            reference_temp.unlink()

    denominator = max(1, sample_count)
    return SeparationPostprocessReport(
        sample_rate=source_info.samplerate,
        channels=source_info.channels,
        frames=vocals_info.frames,
        residual_rms_before=(residual_energy_before / denominator) ** 0.5,
        residual_rms_after=(residual_energy_after / denominator) ** 0.5,
        peak=peak,
    )


def _matching_reference(source: Path, stem_info: object, target: Path) -> Path:
    try:
        source_info = sf.info(source)
    except (OSError, RuntimeError):
        source_info = None
    if (
        source_info is not None
        and source_info.samplerate == stem_info.samplerate
        and source_info.channels == stem_info.channels
        and source_info.frames == stem_info.frames
    ):
        return source

    try:
        ffmpeg = require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise SeparationPostprocessError(str(exc)) from exc
    completed = run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ar",
            str(stem_info.samplerate),
            "-ac",
            str(stem_info.channels),
            "-c:a",
            "pcm_f32le",
            str(target),
        ]
    )
    if completed.returncode != 0 or not target.is_file():
        if target.exists():
            target.unlink()
        raise SeparationPostprocessError(
            f"Could not decode the source for stem alignment: {completed.output}"
        )
    return target


def replace_stem_pair(
    vocals_temp: Path,
    vocals: Path,
    instrumental_temp: Path,
    instrumental: Path,
) -> None:
    vocals_backup = vocals.with_suffix(".pre-consistency.bak.wav")
    instrumental_backup = instrumental.with_suffix(".pre-consistency.bak.wav")
    try:
        if vocals.exists():
            shutil.copy2(vocals, vocals_backup)
        if instrumental.exists():
            shutil.copy2(instrumental, instrumental_backup)
        os.replace(vocals_temp, vocals)
        os.replace(instrumental_temp, instrumental)
    except OSError:
        if vocals_backup.exists():
            os.replace(vocals_backup, vocals)
        elif vocals.exists():
            vocals.unlink()
        if instrumental_backup.exists():
            os.replace(instrumental_backup, instrumental)
        elif instrumental.exists():
            instrumental.unlink()
        raise
    finally:
        for backup in (vocals_backup, instrumental_backup):
            if backup.exists():
                backup.unlink()
