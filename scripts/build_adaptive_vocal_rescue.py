from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Use a secondary separator only where the primary separator drops vocals."
    )
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--rescue", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-vocals", type=Path, required=True)
    parser.add_argument("--output-accompaniment", type=Path, required=True)
    parser.add_argument("--dropout-start-db", type=float, default=4.0)
    parser.add_argument("--dropout-full-db", type=float, default=10.0)
    parser.add_argument("--frame-ms", type=int, default=50)
    parser.add_argument("--attack-ms", type=int, default=75)
    parser.add_argument("--release-ms", type=int, default=250)
    args = parser.parse_args()

    primary, sample_rate = _read(args.primary)
    rescue, rescue_rate = _read(args.rescue)
    source, source_rate = _read(args.source)
    if sample_rate != rescue_rate or sample_rate != source_rate:
        raise ValueError("All inputs must use the same sample rate.")
    if primary.shape != rescue.shape or primary.shape != source.shape:
        raise ValueError(
            f"All inputs must align: {primary.shape}, {rescue.shape}, {source.shape}."
        )
    if args.dropout_full_db <= args.dropout_start_db:
        raise ValueError("--dropout-full-db must be greater than --dropout-start-db.")

    frame_samples = max(1, round(sample_rate * args.frame_ms / 1_000))
    primary_rms = _frame_rms(primary, frame_samples)
    rescue_rms = _frame_rms(rescue, frame_samples)
    dropout_db = 20.0 * np.log10(
        np.maximum(rescue_rms, 1e-9) / np.maximum(primary_rms, 1e-9)
    )
    activity_floor = max(
        10 ** (-52.0 / 20.0),
        float(np.percentile(rescue_rms, 90)) * 0.025,
    )
    activity = np.clip(
        (rescue_rms - activity_floor) / max(activity_floor, 1e-9),
        0.0,
        1.0,
    )
    raw_strength = np.clip(
        (dropout_db - args.dropout_start_db)
        / (args.dropout_full_db - args.dropout_start_db),
        0.0,
        1.0,
    ) * activity
    strength = _smooth(
        raw_strength,
        frame_seconds=frame_samples / sample_rate,
        attack_ms=args.attack_ms,
        release_ms=args.release_ms,
    )
    vocals = _blend(primary, rescue, strength, frame_samples)
    peak_before = float(np.max(np.abs(vocals)))
    peak_gain = min(1.0, 0.98 / max(peak_before, 1e-9))
    vocals *= peak_gain
    accompaniment = source - vocals

    args.output_vocals.parent.mkdir(parents=True, exist_ok=True)
    args.output_accompaniment.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output_vocals, vocals, sample_rate, subtype="FLOAT")
    sf.write(args.output_accompaniment, accompaniment, sample_rate, subtype="FLOAT")

    rescued = strength >= 0.5
    report = {
        "schema": 1,
        "primary": str(args.primary.resolve()),
        "rescue": str(args.rescue.resolve()),
        "source": str(args.source.resolve()),
        "sample_rate": sample_rate,
        "duration_seconds": len(vocals) / sample_rate,
        "active_windows": int(np.count_nonzero(rescue_rms >= activity_floor)),
        "rescued_windows": int(np.count_nonzero(rescued)),
        "rescued_seconds": round(float(np.count_nonzero(rescued) * args.frame_ms / 1_000), 3),
        "maximum_strength": round(float(np.max(strength)), 6),
        "peak_before": peak_before,
        "peak_gain": peak_gain,
        "rescue_ranges": _ranges(rescued, args.frame_ms / 1_000),
        "settings": {
            "dropout_start_db": args.dropout_start_db,
            "dropout_full_db": args.dropout_full_db,
            "frame_ms": args.frame_ms,
            "attack_ms": args.attack_ms,
            "release_ms": args.release_ms,
        },
    }
    args.output_vocals.with_suffix(".json").write_text(
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
    padded = np.zeros((frame_count * frame_samples, audio.shape[1]), dtype=np.float32)
    padded[: len(audio)] = audio
    frames = padded.reshape(frame_count, frame_samples, audio.shape[1])
    return np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=(1, 2)))


def _smooth(
    values: np.ndarray,
    *,
    frame_seconds: float,
    attack_ms: int,
    release_ms: int,
) -> np.ndarray:
    attack = 1.0 - math.exp(-frame_seconds / max(attack_ms / 1_000, 1e-6))
    release = 1.0 - math.exp(-frame_seconds / max(release_ms / 1_000, 1e-6))
    result = np.zeros_like(values)
    current = 0.0
    for index, target in enumerate(values):
        coefficient = attack if target > current else release
        current += coefficient * (float(target) - current)
        result[index] = current
    return result


def _blend(
    primary: np.ndarray,
    rescue: np.ndarray,
    strength: np.ndarray,
    frame_samples: int,
) -> np.ndarray:
    output = np.empty_like(primary)
    previous = float(strength[0]) if strength.size else 0.0
    for index, current_value in enumerate(strength):
        start = index * frame_samples
        end = min(len(primary), start + frame_samples)
        if start >= end:
            break
        current = float(current_value)
        mix = np.linspace(previous, current, end - start, dtype=np.float32)[:, None]
        output[start:end] = primary[start:end] + mix * (
            rescue[start:end] - primary[start:end]
        )
        previous = current
    return output


def _ranges(mask: np.ndarray, frame_seconds: float) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []
    start: int | None = None
    for index, enabled in enumerate(np.append(mask, False)):
        if enabled and start is None:
            start = index
        elif not enabled and start is not None:
            ranges.append(
                {
                    "start_seconds": round(start * frame_seconds, 3),
                    "end_seconds": round(index * frame_seconds, 3),
                }
            )
            start = None
    return ranges


if __name__ == "__main__":
    raise SystemExit(main())
