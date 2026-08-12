from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


FRAME_MS = 50


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an aligned vocal estimate against a known reference."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--estimate", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    reference, sample_rate = _read(args.reference)
    estimate, estimate_rate = _read(args.estimate)
    if estimate_rate != sample_rate:
        divisor = math.gcd(estimate_rate, sample_rate)
        estimate = resample_poly(
            estimate,
            sample_rate // divisor,
            estimate_rate // divisor,
            axis=0,
        ).astype(np.float32)
    if reference.shape[1] != estimate.shape[1]:
        if estimate.shape[1] == 1:
            estimate = np.repeat(estimate, reference.shape[1], axis=1)
        elif reference.shape[1] == 1:
            reference = np.repeat(reference, estimate.shape[1], axis=1)
        else:
            estimate = estimate[:, : reference.shape[1]]
    frames = min(len(reference), len(estimate))
    reference = reference[:frames].astype(np.float64)
    estimate = estimate[:frames].astype(np.float64)

    reference_flat = reference.reshape(-1)
    estimate_flat = estimate.reshape(-1)
    reference_energy = float(np.dot(reference_flat, reference_flat))
    scale = float(np.dot(estimate_flat, reference_flat)) / max(reference_energy, 1e-12)
    projection = reference_flat * scale
    error = estimate_flat - projection
    si_sdr = 10.0 * math.log10(
        max(float(np.dot(projection, projection)), 1e-12)
        / max(float(np.dot(error, error)), 1e-12)
    )
    direct_error = estimate_flat - reference_flat
    sdr = 10.0 * math.log10(
        max(reference_energy, 1e-12)
        / max(float(np.dot(direct_error, direct_error)), 1e-12)
    )
    correlation = float(np.dot(reference_flat, estimate_flat)) / max(
        math.sqrt(reference_energy * float(np.dot(estimate_flat, estimate_flat))),
        1e-12,
    )

    frame_samples = max(1, round(sample_rate * FRAME_MS / 1_000))
    reference_rms = _frame_rms(reference, frame_samples)
    estimate_rms = _frame_rms(estimate, frame_samples)
    active_floor = max(10 ** (-48.0 / 20.0), float(np.percentile(reference_rms, 90)) * 0.03)
    active = reference_rms >= active_floor
    delta_db = 20.0 * np.log10(
        np.maximum(estimate_rms, 1e-9) / np.maximum(reference_rms, 1e-9)
    )
    report = {
        "schema": 1,
        "reference": str(args.reference.resolve()),
        "estimate": str(args.estimate.resolve()),
        "sample_rate": sample_rate,
        "duration_seconds": frames / sample_rate,
        "si_sdr_db": round(si_sdr, 4),
        "sdr_db": round(sdr, 4),
        "waveform_correlation": round(correlation, 6),
        "scale": round(scale, 6),
        "active_frame_percent": round(float(np.mean(active) * 100.0), 3),
        "dropout_frame_percent": round(float(np.mean(delta_db[active] <= -6.0) * 100.0), 3),
        "excess_frame_percent": round(float(np.mean(delta_db[active] >= 6.0) * 100.0), 3),
        "median_level_delta_db": round(float(np.median(delta_db[active])), 4),
        "p95_absolute_level_delta_db": round(
            float(np.percentile(np.abs(delta_db[active]), 95)),
            4,
        ),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _read(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    return audio, int(sample_rate)


def _frame_rms(audio: np.ndarray, frame_samples: int) -> np.ndarray:
    frame_count = math.ceil(len(audio) / frame_samples)
    padded = np.zeros((frame_count * frame_samples, audio.shape[1]), dtype=np.float64)
    padded[: len(audio)] = audio
    frames = padded.reshape(frame_count, frame_samples, audio.shape[1])
    return np.sqrt(np.mean(np.square(frames), axis=(1, 2)))


if __name__ == "__main__":
    raise SystemExit(main())
