from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


FRAME_MS = 50
ACTIVE_FLOOR_DB = -48.0
DISAGREEMENT_WINDOW_SECONDS = 4.0


@dataclass(frozen=True)
class CandidateMetrics:
    name: str
    sample_rate: int
    duration_seconds: float
    peak_dbfs: float
    rms_dbfs: float
    clipped_sample_percent: float
    active_frame_percent: float
    vocal_energy_percent: float
    stereo_side_percent: float
    high_frequency_percent: float
    median_consensus_level_ratio: float
    low_consensus_level_percent: float
    high_consensus_level_percent: float
    mixture_residual_dbfs: float | None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare aligned vocal-separation candidates without a reference stem."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="NAME=VOCALS[|ACCOMPANIMENT]",
        help=(
            "Candidate audio paths. Use '|' between vocals and accompaniment; "
            "the legacy ':' separator remains available for paths without a drive letter."
        ),
    )
    parser.add_argument("--top-windows", type=int, default=8)
    args = parser.parse_args()

    candidates = [_parse_candidate(value) for value in args.candidate]
    if len(candidates) < 2:
        parser.error("At least two --candidate values are required.")

    source, sample_rate = _read_audio(args.source)
    loaded: dict[str, tuple[np.ndarray, np.ndarray | None]] = {}
    frame_count = len(source)
    for name, vocal_path, accompaniment_path in candidates:
        vocals, vocal_rate = _read_audio(vocal_path)
        if vocal_rate != sample_rate:
            raise ValueError(f"{name}: sample rate {vocal_rate} does not match {sample_rate}.")
        accompaniment = None
        if accompaniment_path is not None:
            accompaniment, accompaniment_rate = _read_audio(accompaniment_path)
            if accompaniment_rate != sample_rate:
                raise ValueError(
                    f"{name}: accompaniment sample rate {accompaniment_rate} "
                    f"does not match {sample_rate}."
                )
            frame_count = min(frame_count, len(accompaniment))
        frame_count = min(frame_count, len(vocals))
        loaded[name] = (vocals, accompaniment)

    source = source[:frame_count]
    loaded = {
        name: (
            vocals[:frame_count],
            accompaniment[:frame_count] if accompaniment is not None else None,
        )
        for name, (vocals, accompaniment) in loaded.items()
    }
    frame_samples = max(1, round(sample_rate * FRAME_MS / 1_000))
    source_levels = _frame_rms(source, frame_samples)
    vocal_levels = {
        name: _frame_rms(vocals, frame_samples)
        for name, (vocals, _accompaniment) in loaded.items()
    }
    consensus_levels = np.median(np.stack(tuple(vocal_levels.values())), axis=0)
    active_floor = max(
        _db_to_amplitude(ACTIVE_FLOOR_DB),
        float(np.percentile(source_levels, 90)) * 0.02,
    )
    active_mask = source_levels >= active_floor

    metrics = [
        _candidate_metrics(
            name,
            source,
            vocals,
            accompaniment,
            sample_rate,
            vocal_levels[name],
            consensus_levels,
            active_mask,
        )
        for name, (vocals, accompaniment) in loaded.items()
    ]
    pairwise = _pairwise_metrics(loaded, active_mask, frame_samples)
    disagreement = _disagreement_windows(
        source_levels,
        vocal_levels,
        sample_rate=sample_rate,
        frame_samples=frame_samples,
        count=max(1, args.top_windows),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": 1,
        "source": str(args.source.resolve()),
        "sample_rate": sample_rate,
        "duration_seconds": frame_count / sample_rate,
        "limitations": (
            "No clean reference stem is available. Metrics describe level stability, "
            "candidate agreement, clipping, bandwidth, and mixture reconstruction; "
            "they do not replace a perceptual listening test."
        ),
        "candidates": [asdict(value) for value in metrics],
        "pairwise": pairwise,
        "disagreement_windows": disagreement,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_candidate_csv(args.output_dir / "candidate_metrics.csv", metrics)
    _write_window_csv(args.output_dir / "disagreement_windows.csv", disagreement)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _parse_candidate(value: str) -> tuple[str, Path, Path | None]:
    name, separator, paths = value.partition("=")
    if not separator or not name.strip() or not paths.strip():
        raise ValueError(f"Invalid candidate: {value}")
    path_separator = "|" if "|" in paths else ":"
    vocal_text, accompaniment_separator, accompaniment_text = paths.partition(
        path_separator
    )
    if not vocal_text.strip() or (accompaniment_separator and not accompaniment_text.strip()):
        raise ValueError(f"Invalid candidate paths: {value}")
    return (
        name.strip(),
        Path(vocal_text.strip()),
        Path(accompaniment_text.strip()) if accompaniment_separator else None,
    )


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if audio.size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return audio, sample_rate


def _candidate_metrics(
    name: str,
    source: np.ndarray,
    vocals: np.ndarray,
    accompaniment: np.ndarray | None,
    sample_rate: int,
    levels: np.ndarray,
    consensus_levels: np.ndarray,
    active_mask: np.ndarray,
) -> CandidateMetrics:
    safe_consensus = np.maximum(consensus_levels, 1e-9)
    ratios = levels / safe_consensus
    active_ratios = ratios[active_mask]
    residual_dbfs = None
    if accompaniment is not None:
        residual = source - vocals - accompaniment
        residual_dbfs = _amplitude_to_db(_rms(residual))
    return CandidateMetrics(
        name=name,
        sample_rate=sample_rate,
        duration_seconds=round(len(vocals) / sample_rate, 3),
        peak_dbfs=round(_amplitude_to_db(float(np.max(np.abs(vocals)))), 3),
        rms_dbfs=round(_amplitude_to_db(_rms(vocals)), 3),
        clipped_sample_percent=round(
            float(np.mean(np.abs(vocals) >= 0.999)) * 100,
            5,
        ),
        active_frame_percent=round(float(np.mean(levels >= _db_to_amplitude(-48))) * 100, 3),
        vocal_energy_percent=round(
            float(np.sum(np.square(vocals, dtype=np.float64)))
            / max(float(np.sum(np.square(source, dtype=np.float64))), 1e-12)
            * 100,
            3,
        ),
        stereo_side_percent=round(_stereo_side_percent(vocals), 3),
        high_frequency_percent=round(_high_frequency_percent(vocals, sample_rate), 3),
        median_consensus_level_ratio=round(float(np.median(active_ratios)), 4),
        low_consensus_level_percent=round(float(np.mean(active_ratios < 0.55)) * 100, 3),
        high_consensus_level_percent=round(float(np.mean(active_ratios > 1.45)) * 100, 3),
        mixture_residual_dbfs=(round(residual_dbfs, 3) if residual_dbfs is not None else None),
    )


def _pairwise_metrics(
    loaded: dict[str, tuple[np.ndarray, np.ndarray | None]],
    active_mask: np.ndarray,
    frame_samples: int,
) -> list[dict[str, float | str]]:
    results: list[dict[str, float | str]] = []
    names = tuple(loaded)
    for left_index, left_name in enumerate(names):
        left = loaded[left_name][0]
        left_levels = _frame_rms(left, frame_samples)[active_mask]
        for right_name in names[left_index + 1 :]:
            right = loaded[right_name][0]
            right_levels = _frame_rms(right, frame_samples)[active_mask]
            waveform_correlation = _correlation(left.reshape(-1), right.reshape(-1))
            envelope_correlation = _correlation(left_levels, right_levels)
            level_delta = np.abs(
                20 * np.log10(np.maximum(left_levels, 1e-9))
                - 20 * np.log10(np.maximum(right_levels, 1e-9))
            )
            results.append(
                {
                    "left": left_name,
                    "right": right_name,
                    "waveform_correlation": round(waveform_correlation, 5),
                    "level_envelope_correlation": round(envelope_correlation, 5),
                    "median_absolute_level_delta_db": round(float(np.median(level_delta)), 3),
                    "p95_absolute_level_delta_db": round(float(np.percentile(level_delta, 95)), 3),
                }
            )
    return results


def _disagreement_windows(
    source_levels: np.ndarray,
    vocal_levels: dict[str, np.ndarray],
    *,
    sample_rate: int,
    frame_samples: int,
    count: int,
) -> list[dict[str, object]]:
    names = tuple(vocal_levels)
    stacked_db = 20 * np.log10(np.maximum(np.stack(tuple(vocal_levels.values())), 1e-9))
    spread_db = np.max(stacked_db, axis=0) - np.min(stacked_db, axis=0)
    source_db = 20 * np.log10(np.maximum(source_levels, 1e-9))
    spread_db = np.where(source_db >= ACTIVE_FLOOR_DB, spread_db, 0.0)
    window_frames = max(1, round(DISAGREEMENT_WINDOW_SECONDS * sample_rate / frame_samples))
    kernel = np.ones(window_frames, dtype=np.float64) / window_frames
    scores = np.convolve(spread_db, kernel, mode="same")
    selected: list[int] = []
    suppression = max(1, window_frames)
    mutable = scores.copy()
    for _index in range(count):
        center = int(np.argmax(mutable))
        if mutable[center] <= 0:
            break
        selected.append(center)
        mutable[max(0, center - suppression) : center + suppression + 1] = -1

    results: list[dict[str, object]] = []
    for center in sorted(selected):
        start_frame = max(0, center - window_frames // 2)
        end_frame = min(len(source_levels), start_frame + window_frames)
        levels = {
            name: round(
                _amplitude_to_db(float(np.sqrt(np.mean(np.square(values[start_frame:end_frame]))))),
                3,
            )
            for name, values in vocal_levels.items()
        }
        results.append(
            {
                "start_seconds": round(start_frame * frame_samples / sample_rate, 3),
                "end_seconds": round(end_frame * frame_samples / sample_rate, 3),
                "average_spread_db": round(float(np.mean(spread_db[start_frame:end_frame])), 3),
                "vocal_level_dbfs": levels,
                "loudest_candidate": max(levels, key=levels.get),
                "quietest_candidate": min(levels, key=levels.get),
            }
        )
    return results


def _frame_rms(audio: np.ndarray, frame_samples: int) -> np.ndarray:
    frame_count = math.ceil(len(audio) / frame_samples)
    padded = np.zeros((frame_count * frame_samples, audio.shape[1]), dtype=np.float32)
    padded[: len(audio)] = audio
    framed = padded.reshape(frame_count, frame_samples, audio.shape[1])
    return np.sqrt(np.mean(np.square(framed, dtype=np.float64), axis=(1, 2)))


def _stereo_side_percent(audio: np.ndarray) -> float:
    if audio.shape[1] < 2:
        return 0.0
    mid = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5
    return float(np.sum(np.square(side, dtype=np.float64))) / max(
        float(np.sum(np.square(mid, dtype=np.float64))),
        1e-12,
    ) * 100


def _high_frequency_percent(audio: np.ndarray, sample_rate: int) -> float:
    mono = np.mean(audio, axis=1)
    frame_size = 4096
    hop = 2048
    if len(mono) < frame_size:
        return 0.0
    window = np.hanning(frame_size).astype(np.float32)
    high_energy = 0.0
    total_energy = 0.0
    high_start = math.ceil(5_000 * frame_size / sample_rate)
    for start in range(0, len(mono) - frame_size + 1, hop):
        spectrum = np.fft.rfft(mono[start : start + frame_size] * window)
        energy = np.square(np.abs(spectrum), dtype=np.float64)
        total_energy += float(np.sum(energy))
        high_energy += float(np.sum(energy[high_start:]))
    return high_energy / max(total_energy, 1e-12) * 100


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    left_centered = left.astype(np.float64) - float(np.mean(left))
    right_centered = right.astype(np.float64) - float(np.mean(right))
    denominator = math.sqrt(
        float(np.sum(np.square(left_centered)))
        * float(np.sum(np.square(right_centered)))
    )
    if denominator <= 1e-12:
        return 0.0
    return float(np.sum(left_centered * right_centered) / denominator)


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def _db_to_amplitude(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _amplitude_to_db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-9))


def _write_candidate_csv(path: Path, metrics: list[CandidateMetrics]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(asdict(metrics[0])))
        writer.writeheader()
        writer.writerows(asdict(value) for value in metrics)


def _write_window_csv(path: Path, windows: list[dict[str, object]]) -> None:
    fieldnames = ("start_seconds", "end_seconds", "average_spread_db", "loudest_candidate", "quietest_candidate", "vocal_level_dbfs")
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for value in windows:
            row = dict(value)
            row["vocal_level_dbfs"] = json.dumps(row["vocal_level_dbfs"], ensure_ascii=False)
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
