from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.managed_files import write_json_atomic


class SeparationQualityError(RuntimeError):
    """Raised when reference and estimated stems cannot be compared."""


@dataclass(frozen=True)
class StemQualityMetrics:
    si_sdr_db: float
    peak: float
    clipped_ratio: float


@dataclass(frozen=True)
class SeparationQualityReport:
    sample_rate: int
    frames: int
    channels: int
    vocals: StemQualityMetrics
    instrumental: StemQualityMetrics
    mixture_residual_rms: float

    @property
    def mean_si_sdr_db(self) -> float:
        return (self.vocals.si_sdr_db + self.instrumental.si_sdr_db) / 2.0


def measure_separation_quality(
    reference_vocals_path: Path,
    reference_instrumental_path: Path,
    estimated_vocals_path: Path,
    estimated_instrumental_path: Path,
) -> SeparationQualityReport:
    reference_vocals, rate = _read_audio(reference_vocals_path)
    reference_instrumental, instrumental_rate = _read_audio(reference_instrumental_path)
    estimated_vocals, estimated_vocals_rate = _read_audio(estimated_vocals_path)
    estimated_instrumental, estimated_instrumental_rate = _read_audio(
        estimated_instrumental_path
    )
    rates = {rate, instrumental_rate, estimated_vocals_rate, estimated_instrumental_rate}
    shapes = {
        reference_vocals.shape,
        reference_instrumental.shape,
        estimated_vocals.shape,
        estimated_instrumental.shape,
    }
    if len(rates) != 1 or len(shapes) != 1:
        raise SeparationQualityError(
            "Reference and estimated stems must have identical sample rates, channels, and lengths."
        )

    reference_mix = reference_vocals + reference_instrumental
    estimated_mix = estimated_vocals + estimated_instrumental
    return SeparationQualityReport(
        sample_rate=rate,
        frames=reference_vocals.shape[0],
        channels=reference_vocals.shape[1],
        vocals=_stem_metrics(reference_vocals, estimated_vocals),
        instrumental=_stem_metrics(reference_instrumental, estimated_instrumental),
        mixture_residual_rms=float(
            np.sqrt(np.mean(np.square(reference_mix - estimated_mix, dtype=np.float64)))
        ),
    )


def save_quality_report(path: Path, report: SeparationQualityReport) -> Path:
    target = path.expanduser().resolve()
    data = asdict(report)
    data["mean_si_sdr_db"] = report.mean_si_sdr_db
    write_json_atomic(target, data)
    return target


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise SeparationQualityError(f"Audio file does not exist: {source}")
    try:
        audio, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise SeparationQualityError(f"Could not read audio: {source}") from exc
    if not len(audio):
        raise SeparationQualityError(f"Audio file is empty: {source}")
    return audio, sample_rate


def _stem_metrics(reference: np.ndarray, estimate: np.ndarray) -> StemQualityMetrics:
    absolute = np.abs(estimate)
    return StemQualityMetrics(
        si_sdr_db=_si_sdr(reference, estimate),
        peak=float(np.max(absolute)),
        clipped_ratio=float(np.mean(absolute >= 1.0)),
    )


def _si_sdr(reference: np.ndarray, estimate: np.ndarray) -> float:
    reference_vector = reference.astype(np.float64, copy=False).reshape(-1)
    estimate_vector = estimate.astype(np.float64, copy=False).reshape(-1)
    reference_vector = reference_vector - np.mean(reference_vector)
    estimate_vector = estimate_vector - np.mean(estimate_vector)
    reference_energy = float(np.dot(reference_vector, reference_vector))
    if reference_energy <= 1e-12:
        raise SeparationQualityError("A reference stem is silent and cannot be scored.")
    projection = reference_vector * (
        float(np.dot(estimate_vector, reference_vector)) / reference_energy
    )
    noise = estimate_vector - projection
    target_energy = float(np.dot(projection, projection))
    noise_energy = max(float(np.dot(noise, noise)), 1e-12)
    return float(10.0 * np.log10(max(target_energy, 1e-12) / noise_energy))
