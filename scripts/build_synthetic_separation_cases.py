from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly


SAMPLE_RATE = 44_100


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build aligned dry, reverb, and delay separation benchmark mixtures."
    )
    parser.add_argument("--vocal", type=Path, action="append", required=True)
    parser.add_argument("--instrumental", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--instrumental-start", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=20260811)
    args = parser.parse_args()

    frames = max(1, round(args.duration * SAMPLE_RATE))
    vocal = _vocal_sequence(args.vocal, frames)
    instrumental = _read_stereo(args.instrumental)
    start = max(0, round(args.instrumental_start * SAMPLE_RATE))
    instrumental = _fit_length(instrumental[start:], frames)

    vocal *= _gain_for_rms(vocal, -19.0)
    instrumental *= _gain_for_rms(instrumental, -18.0)
    cases = {
        "dry": vocal,
        "reverb": _reverb(vocal, args.seed),
        "delay": _delay(vocal),
    }
    report: dict[str, object] = {
        "schema": 1,
        "sample_rate": SAMPLE_RATE,
        "duration_seconds": args.duration,
        "vocal_sources": [str(path.resolve()) for path in args.vocal],
        "instrumental": str(args.instrumental.resolve()),
        "cases": {},
    }
    for name, target_vocal in cases.items():
        target_vocal *= _gain_for_rms(target_vocal, -19.0)
        mixture = target_vocal + instrumental
        common_gain = min(1.0, 0.96 / max(float(np.max(np.abs(mixture))), 1e-9))
        case_dir = args.output_dir / name
        case_dir.mkdir(parents=True, exist_ok=True)
        _write(case_dir / "mixture.wav", mixture * common_gain)
        _write(case_dir / "vocal-reference.wav", target_vocal * common_gain)
        _write(case_dir / "instrumental-reference.wav", instrumental * common_gain)
        report["cases"][name] = {
            "common_gain": common_gain,
            "mixture_peak": float(np.max(np.abs(mixture * common_gain))),
        }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "cases.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _vocal_sequence(paths: list[Path], frames: int) -> np.ndarray:
    clips = [_trim_silence(_read_stereo(path)) for path in paths]
    gap = np.zeros((round(0.12 * SAMPLE_RATE), 2), dtype=np.float32)
    parts: list[np.ndarray] = []
    current = 0
    index = 0
    while current < frames:
        clip = clips[index % len(clips)]
        parts.extend((clip, gap))
        current += len(clip) + len(gap)
        index += 1
    return _fit_length(np.concatenate(parts, axis=0), frames)


def _read_stereo(path: Path) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if sample_rate != SAMPLE_RATE:
        divisor = math.gcd(int(sample_rate), SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // divisor,
            int(sample_rate) // divisor,
            axis=0,
        ).astype(np.float32)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    return audio[:, :2]


def _trim_silence(audio: np.ndarray) -> np.ndarray:
    mono = np.max(np.abs(audio), axis=1)
    active = np.flatnonzero(mono >= 10 ** (-52.0 / 20.0))
    if active.size == 0:
        return audio
    padding = round(0.05 * SAMPLE_RATE)
    start = max(0, int(active[0]) - padding)
    end = min(len(audio), int(active[-1]) + padding + 1)
    return audio[start:end]


def _fit_length(audio: np.ndarray, frames: int) -> np.ndarray:
    if len(audio) >= frames:
        return audio[:frames].copy()
    repeats = math.ceil(frames / max(len(audio), 1))
    return np.tile(audio, (repeats, 1))[:frames].copy()


def _gain_for_rms(audio: np.ndarray, target_dbfs: float) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return 10 ** (target_dbfs / 20.0) / max(rms, 1e-9)


def _reverb(audio: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    length = round(1.5 * SAMPLE_RATE)
    result = np.zeros_like(audio)
    for channel in range(2):
        times = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        impulse = rng.normal(0.0, 1.0, length).astype(np.float32)
        impulse *= np.exp(-times * 3.4) * 0.012
        impulse[0] += 1.0
        for delay_ms, gain in ((63, 0.30), (137, 0.20), (271, 0.12)):
            impulse[round(delay_ms * SAMPLE_RATE / 1_000)] += gain
        result[:, channel] = fftconvolve(audio[:, channel], impulse, mode="full")[: len(audio)]
    return result


def _delay(audio: np.ndarray) -> np.ndarray:
    result = audio.copy()
    for delay_ms, gain in ((240, 0.34), (480, 0.18), (720, 0.09)):
        delay = round(delay_ms * SAMPLE_RATE / 1_000)
        result[delay:] += audio[:-delay] * gain
    return result


def _write(path: Path, audio: np.ndarray) -> None:
    sf.write(path, audio, SAMPLE_RATE, subtype="FLOAT")


if __name__ == "__main__":
    raise SystemExit(main())
