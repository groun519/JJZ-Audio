from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


FRAME_MS = 50
ATTACK_MS = 75
RELEASE_MS = 200


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Blend a dry-vocal estimate only where it agrees with the wet vocal."
    )
    parser.add_argument("--wet", type=Path, required=True)
    parser.add_argument("--dry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-strength", type=float, default=0.75)
    parser.add_argument("--ratio-start", type=float, default=0.70)
    parser.add_argument("--ratio-full", type=float, default=0.90)
    parser.add_argument("--correlation-start", type=float, default=0.65)
    parser.add_argument("--correlation-full", type=float, default=0.90)
    parser.add_argument("--target-ratio", type=float, default=0.94)
    parser.add_argument("--max-dry-gain", type=float, default=1.35)
    args = parser.parse_args()

    wet, sample_rate = sf.read(args.wet, dtype="float32", always_2d=True)
    dry, dry_rate = sf.read(args.dry, dtype="float32", always_2d=True)
    if sample_rate != dry_rate or wet.shape != dry.shape:
        raise ValueError(
            f"Wet and dry vocals must align, got {sample_rate}/{wet.shape} "
            f"and {dry_rate}/{dry.shape}."
        )
    if not 0.0 <= args.max_strength <= 1.0:
        raise ValueError("--max-strength must be between 0 and 1.")

    frame_samples = max(1, round(sample_rate * FRAME_MS / 1_000))
    wet_rms, dry_rms, correlation = _frame_analysis(wet, dry, frame_samples)
    ratio = dry_rms / np.maximum(wet_rms, 1e-9)
    active_floor = max(10 ** (-48 / 20), float(np.percentile(wet_rms, 90)) * 0.04)
    activity = np.clip((wet_rms - active_floor) / max(active_floor, 1e-9), 0.0, 1.0)
    ratio_trust = _range_score(ratio, args.ratio_start, args.ratio_full)
    correlation_trust = _range_score(
        correlation,
        args.correlation_start,
        args.correlation_full,
    )
    trust = np.minimum(ratio_trust, correlation_trust) * activity
    strength = _smooth(
        trust * args.max_strength,
        frame_seconds=frame_samples / sample_rate,
    )

    desired_gain = args.target_ratio / np.maximum(ratio, 1e-9)
    dry_gain = 1.0 + trust * (
        np.clip(desired_gain, 1.0, args.max_dry_gain) - 1.0
    )
    output = _render(wet, dry, strength, dry_gain, frame_samples)
    peak_before = float(np.max(np.abs(output)))
    peak_gain = min(1.0, 0.98 / max(peak_before, 1e-9))
    output *= peak_gain

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, output, sample_rate, subtype="FLOAT")
    report = {
        "schema": 1,
        "wet": str(args.wet.resolve()),
        "dry": str(args.dry.resolve()),
        "sample_rate": sample_rate,
        "frames": len(wet),
        "active_windows": int(np.count_nonzero(wet_rms >= active_floor)),
        "trusted_windows": int(np.count_nonzero(trust >= 0.5)),
        "average_strength_active": float(np.mean(strength[wet_rms >= active_floor])),
        "maximum_strength": float(np.max(strength)),
        "average_dry_gain_trusted": float(np.mean(dry_gain[trust >= 0.5]))
        if np.any(trust >= 0.5)
        else 1.0,
        "peak_before": peak_before,
        "peak_gain": peak_gain,
        "settings": {
            "max_strength": args.max_strength,
            "ratio_start": args.ratio_start,
            "ratio_full": args.ratio_full,
            "correlation_start": args.correlation_start,
            "correlation_full": args.correlation_full,
            "target_ratio": args.target_ratio,
            "max_dry_gain": args.max_dry_gain,
        },
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _frame_analysis(
    wet: np.ndarray,
    dry: np.ndarray,
    frame_samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame_count = math.ceil(len(wet) / frame_samples)
    padded_frames = frame_count * frame_samples
    wet_padded = np.zeros((padded_frames, wet.shape[1]), dtype=np.float32)
    dry_padded = np.zeros((padded_frames, dry.shape[1]), dtype=np.float32)
    wet_padded[: len(wet)] = wet
    dry_padded[: len(dry)] = dry
    wet_frames = wet_padded.reshape(frame_count, frame_samples, wet.shape[1])
    dry_frames = dry_padded.reshape(frame_count, frame_samples, dry.shape[1])
    wet_energy = np.sum(np.square(wet_frames, dtype=np.float64), axis=(1, 2))
    dry_energy = np.sum(np.square(dry_frames, dtype=np.float64), axis=(1, 2))
    sample_count = frame_samples * wet.shape[1]
    wet_rms = np.sqrt(wet_energy / sample_count)
    dry_rms = np.sqrt(dry_energy / sample_count)
    correlation = np.sum(wet_frames * dry_frames, axis=(1, 2)) / np.maximum(
        np.sqrt(wet_energy * dry_energy),
        1e-9,
    )
    return wet_rms, dry_rms, correlation


def _range_score(values: np.ndarray, start: float, full: float) -> np.ndarray:
    if full <= start:
        raise ValueError("A full threshold must be greater than its start threshold.")
    return np.clip((values - start) / (full - start), 0.0, 1.0)


def _smooth(values: np.ndarray, *, frame_seconds: float) -> np.ndarray:
    attack = 1.0 - math.exp(-frame_seconds / (ATTACK_MS / 1_000))
    release = 1.0 - math.exp(-frame_seconds / (RELEASE_MS / 1_000))
    result = np.zeros_like(values)
    current = 0.0
    for index, target in enumerate(values):
        coefficient = attack if target > current else release
        current += coefficient * (float(target) - current)
        result[index] = current
    return result


def _render(
    wet: np.ndarray,
    dry: np.ndarray,
    strength: np.ndarray,
    dry_gain: np.ndarray,
    frame_samples: int,
) -> np.ndarray:
    output = np.empty_like(wet)
    previous_strength = float(strength[0]) if strength.size else 0.0
    previous_gain = float(dry_gain[0]) if dry_gain.size else 1.0
    for index in range(len(strength)):
        start = index * frame_samples
        end = min(len(wet), start + frame_samples)
        if start >= end:
            break
        count = end - start
        current_strength = float(strength[index])
        current_gain = float(dry_gain[index])
        mix = np.linspace(
            previous_strength,
            current_strength,
            count,
            dtype=np.float32,
        )[:, None]
        gain = np.linspace(
            previous_gain,
            current_gain,
            count,
            dtype=np.float32,
        )[:, None]
        compensated_dry = dry[start:end] * gain
        output[start:end] = wet[start:end] + mix * (compensated_dry - wet[start:end])
        previous_strength = current_strength
        previous_gain = current_gain
    return output


if __name__ == "__main__":
    raise SystemExit(main())
