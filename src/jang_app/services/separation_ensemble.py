from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf

from jang_app.services.separation_postprocess import replace_stem_pair


_BLOCK_FRAMES = 262_144


class SeparationEnsembleError(RuntimeError):
    """Raised when compatible separation stems cannot be combined safely."""


@dataclass(frozen=True)
class SeparationStemPair:
    vocals_path: Path
    instrumental_path: Path


@dataclass(frozen=True)
class SeparationEnsembleReport:
    members: int
    sample_rate: int
    channels: int
    frames: int
    peak: float


def blend_stem_pairs(
    stem_pairs: Sequence[SeparationStemPair],
    vocals_path: Path,
    instrumental_path: Path,
    *,
    weights: Sequence[float] = (),
) -> SeparationEnsembleReport:
    members = tuple(stem_pairs)
    if len(members) < 2:
        raise SeparationEnsembleError("A separation ensemble requires at least two stem pairs.")
    normalized_weights = _normalized_weights(len(members), weights)
    member_info = tuple(_stem_pair_info(pair) for pair in members)
    expected = member_info[0]
    if any(info != expected for info in member_info[1:]):
        raise SeparationEnsembleError(
            "All ensemble stems must have the same sample rate, channels, and length."
        )

    sample_rate, channels, frames = expected
    if frames <= 0:
        raise SeparationEnsembleError("Ensemble stems cannot be empty.")
    vocals = vocals_path.expanduser().resolve()
    instrumental = instrumental_path.expanduser().resolve()
    if vocals.parent != instrumental.parent:
        raise SeparationEnsembleError("Ensemble outputs must share one directory.")
    vocals.parent.mkdir(parents=True, exist_ok=True)
    vocals_temp = vocals.with_suffix(".ensemble.tmp.wav")
    instrumental_temp = instrumental.with_suffix(".ensemble.tmp.wav")
    peak = 0.0
    try:
        with ExitStack() as stack:
            vocal_inputs = [stack.enter_context(sf.SoundFile(pair.vocals_path)) for pair in members]
            instrumental_inputs = [
                stack.enter_context(sf.SoundFile(pair.instrumental_path)) for pair in members
            ]
            vocal_output = stack.enter_context(
                sf.SoundFile(
                    vocals_temp,
                    mode="w",
                    samplerate=sample_rate,
                    channels=channels,
                    subtype="FLOAT",
                )
            )
            instrumental_output = stack.enter_context(
                sf.SoundFile(
                    instrumental_temp,
                    mode="w",
                    samplerate=sample_rate,
                    channels=channels,
                    subtype="FLOAT",
                )
            )
            remaining = frames
            while remaining > 0:
                block_frames = min(_BLOCK_FRAMES, remaining)
                vocal_block = _weighted_block(vocal_inputs, normalized_weights, block_frames)
                instrumental_block = _weighted_block(
                    instrumental_inputs,
                    normalized_weights,
                    block_frames,
                )
                vocal_output.write(vocal_block)
                instrumental_output.write(instrumental_block)
                peak = max(
                    peak,
                    float(np.max(np.abs(vocal_block))),
                    float(np.max(np.abs(instrumental_block))),
                )
                remaining -= block_frames
        replace_stem_pair(vocals_temp, vocals, instrumental_temp, instrumental)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SeparationEnsembleError(f"Could not combine separation stems: {exc}") from exc
    finally:
        for temporary in (vocals_temp, instrumental_temp):
            if temporary.exists():
                temporary.unlink()

    return SeparationEnsembleReport(
        members=len(members),
        sample_rate=sample_rate,
        channels=channels,
        frames=frames,
        peak=peak,
    )


def _normalized_weights(member_count: int, weights: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(weight) for weight in weights) if weights else (1.0,) * member_count
    if len(values) != member_count or any(weight <= 0 for weight in values):
        raise SeparationEnsembleError("Ensemble weights must be positive and match its members.")
    total = sum(values)
    return tuple(weight / total for weight in values)


def _stem_pair_info(pair: SeparationStemPair) -> tuple[int, int, int]:
    try:
        vocals = sf.info(pair.vocals_path)
        instrumental = sf.info(pair.instrumental_path)
    except (OSError, RuntimeError) as exc:
        raise SeparationEnsembleError(f"Could not read an ensemble stem: {exc}") from exc
    vocal_info = (vocals.samplerate, vocals.channels, vocals.frames)
    instrumental_info = (
        instrumental.samplerate,
        instrumental.channels,
        instrumental.frames,
    )
    if vocal_info != instrumental_info:
        raise SeparationEnsembleError(
            "Each vocal and instrumental stem pair must have matching audio properties."
        )
    return vocal_info


def _weighted_block(
    inputs: Sequence[sf.SoundFile],
    weights: Sequence[float],
    frames: int,
) -> np.ndarray:
    output: np.ndarray | None = None
    for source, weight in zip(inputs, weights, strict=True):
        block = source.read(frames, dtype="float32", always_2d=True)
        if len(block) != frames:
            raise SeparationEnsembleError("An ensemble stem ended before its declared length.")
        weighted = block * weight
        output = weighted if output is None else output + weighted
    if output is None:
        raise SeparationEnsembleError("No ensemble audio was available.")
    return output
